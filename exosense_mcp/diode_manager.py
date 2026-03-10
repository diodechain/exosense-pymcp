"""
Minimal Diode CLI integration for ExoSense MCP server.
Spawns Diode CLI to publish the MCP server's port publicly (https://<client>.diode.link:PORT/mcp).
Pattern from mcp-example; no external Diode client coordination needed.
"""
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional, Dict, List

import yaml

# Default start of range when searching for a free Diode API port (overridable via config)
DEFAULT_DIODE_API_PORT_START = 30000
DEFAULT_JOIN_ADDRESS = "0x0000000000000000000000000000000000000000"

_base_dir = Path(__file__).parent
_project_root = _base_dir.parent
DIODE_CLIENT_DIR = _project_root / "diode_client"
DIODE_DB_PATH = DIODE_CLIENT_DIR / "diode_mcp.db"
DIODE_LOG_FILE = DIODE_CLIENT_DIR / "diode_client.log"

diode_process: Optional[subprocess.Popen] = None
diode_client_identity: Optional[str] = None
diode_error: Optional[str] = None
diode_output: List[str] = []
diode_config_data: Optional[Dict] = None
_actual_api_port: int = 0  # Set when Diode starts; always chosen via find_free_port
_publish_port: int = 9000  # MCP server port to publish
_diode_lock = threading.Lock()
_output_lock = threading.Lock()


def get_config_path() -> Path:
    return _project_root / "config.yml"


def _load_diode_config() -> Dict:
    """Load Diode-related keys from config.yml."""
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            return config if config and isinstance(config, dict) else {}
    except Exception:
        return {}


def load_diode_join_address() -> str:
    cfg = _load_diode_config()
    addr = cfg.get("diode_join_address")
    if addr and isinstance(addr, str) and addr.strip():
        return addr.strip()
    return DEFAULT_JOIN_ADDRESS


def get_diode_api_port_start() -> int:
    """First port to try when finding a free port for the Diode API. From config or default."""
    cfg = _load_diode_config()
    val = cfg.get("diode_api_port_start")
    if val is not None:
        try:
            p = int(val)
            if 1 <= p <= 65535:
                return p
        except (TypeError, ValueError):
            pass
    return DEFAULT_DIODE_API_PORT_START


def set_publish_port(port: int) -> None:
    """Set the port to publish (MCP server port)."""
    global _publish_port
    _publish_port = port


def get_publish_port() -> int:
    return _publish_port


def find_free_port(start_port: int, max_attempts: int = 100) -> Optional[int]:
    for i in range(max_attempts):
        port = start_port + i
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return None


def find_diode_executable() -> Optional[str]:
    project_diode = _project_root / "diode"
    if project_diode.exists() and os.access(project_diode, os.X_OK):
        return str(project_diode)
    import shutil
    path = shutil.which("diode")
    if path:
        return path
    for p in [
        os.path.expanduser("~/opt/diode/diode"),
        "/usr/local/bin/diode",
        "/usr/bin/diode",
        os.path.expanduser("~/bin/diode"),
    ]:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def get_actual_api_url() -> str:
    return f"http://localhost:{_actual_api_port}"


def build_diode_command() -> Optional[list]:
    diode_path = find_diode_executable()
    if not diode_path:
        return None
    is_local = diode_path.endswith("diode") and (
        diode_path == "diode" or Path(diode_path).resolve() == _project_root / "diode"
    )
    join_address = load_diode_join_address()
    api_addr = f"localhost:{_actual_api_port}"
    log_path = str(DIODE_LOG_FILE)
    db_path = str(DIODE_DB_PATH)
    cmd = [
        diode_path,
        "-debug",
        "-api=true",
        f"-apiaddr={api_addr}",
        f"-dbpath={db_path}",
        f"-logfilepath={log_path}",
    ]
    if is_local:
        cmd.append("-update=false")
    if join_address == DEFAULT_JOIN_ADDRESS:
        cmd.extend(["publish", "-public", f"{_publish_port}:{_publish_port}"])
    else:
        cmd.extend(["join", join_address])
    return cmd


def _fetch_config() -> Optional[Dict]:
    global diode_config_data, diode_client_identity, diode_error
    if diode_process is None or diode_process.poll() is not None:
        diode_error = "Diode process is not running"
        diode_config_data = None
        return None
    url = f"{get_actual_api_url()}/config"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status != 200:
                    continue
                data = json.loads(resp.read().decode())
                if data.get("success") and "config" in data:
                    config = data["config"]
                    diode_config_data = config
                    cid = config.get("client")
                    if cid:
                        diode_client_identity = cid
                        diode_error = None
                    return config
        except Exception as e:
            diode_error = str(e)
            if attempt < 4:
                time.sleep(0.5)
            else:
                diode_config_data = None
                return None
    return None


def _is_port_published_in_config(config: Dict) -> bool:
    """
    Return True if the API config shows our port is published (perimeter).
    _publish_port is our local port; the API reports the external port in perimeter.properties.
    For default join (public): client present means published. For join: client + any property.
    """
    if not config or not config.get("client"):
        return False
    join_address = load_diode_join_address()
    if join_address == DEFAULT_JOIN_ADDRESS:
        return True
    perimeter = (config.get("perimeter") or {}) or {}
    props = perimeter.get("properties") or []
    for prop in props:
        if not isinstance(prop, dict):
            continue
        if prop.get("public") or prop.get("private") or prop.get("protected"):
            return True
    return False


def _external_publish_port_from_config(config: Dict) -> Optional[int]:
    """
    Return the external port from API config (what clients use at clientid.diode.link:PORT).
    The API shows the external port, not our local _publish_port. Returns None if not found.
    """
    if not config:
        return None
    perimeter = (config.get("perimeter") or {}) or {}
    props = perimeter.get("properties") or []
    for prop in props:
        if not isinstance(prop, dict):
            continue
        public_val = prop.get("public")
        if public_val:
            s = str(public_val).strip()
            if ":" in s:
                try:
                    return int(s.rsplit(":", 1)[-1].strip())
                except (TypeError, ValueError):
                    pass
            try:
                return int(s)
            except (TypeError, ValueError):
                pass
    return None


def get_client_identity() -> Optional[str]:
    _fetch_config()
    return diode_client_identity


def get_published_mcp_urls(config: Optional[Dict] = None) -> List[str]:
    """Return local and public MCP URLs (with /mcp path). Uses external port from API config when in join mode."""
    local_port = _publish_port
    local = f"http://127.0.0.1:{local_port}/mcp"
    urls = [local]
    client_id = get_client_identity()
    if not client_id:
        return urls
    cfg = config if config is not None else _fetch_config()
    external = _external_publish_port_from_config(cfg) if cfg else None
    port = external if external is not None else local_port
    if load_diode_join_address() == DEFAULT_JOIN_ADDRESS:
        urls.append(f"https://{client_id}.diode.link:{port}/mcp")
    elif cfg and _is_port_published_in_config(cfg):
        urls.append(f"https://{client_id}.diode.link:{port}/mcp")
    return urls


def _print_recent_diode_output(lines: int = 30) -> None:
    """Print recent Diode CLI stdout/stderr to help diagnose startup failures."""
    with _output_lock:
        recent = list(diode_output[-lines:]) if diode_output else []
    if not recent:
        return
    print("  Recent Diode CLI output:", flush=True)
    for line in recent:
        print(f"    {line}", flush=True)


def get_diode_connection_status() -> Dict:
    """Return current Diode connection status for debug output."""
    join_address = load_diode_join_address()
    mode = "join" if join_address != DEFAULT_JOIN_ADDRESS else "public"
    status = {
        "api_url": get_actual_api_url() if _actual_api_port else None,
        "api_port": _actual_api_port or None,
        "client_identity": get_client_identity(),
        "mode": mode,
        "join_address": join_address if mode == "join" else None,
        "publish_port": _publish_port,
        "pid": diode_process.pid if diode_process and diode_process.poll() is None else None,
        "error": diode_error,
    }
    return status


def print_diode_connection_status() -> None:
    """Print Diode connection status to stdout (for debug output)."""
    s = get_diode_connection_status()
    port_start = get_diode_api_port_start()
    print("\n" + "=" * 60, flush=True)
    print("Diode connection status", flush=True)
    print("=" * 60, flush=True)
    print(f"  API URL:            {s['api_url'] or '—'}", flush=True)
    print(f"  Diode API port:      {s['api_port'] or '—'} (auto-selected, search from {port_start})", flush=True)
    print(f"  Client ID:      {s['client_identity'] or '—'}", flush=True)
    print(f"  Mode:           {s['mode']}", flush=True)
    if s.get("join_address"):
        print(f"  Join address:   {s['join_address']}", flush=True)
    print(f"  Publish port:   {s['publish_port']}", flush=True)
    print(f"  Process PID:    {s['pid'] or '—'}", flush=True)
    if s.get("error"):
        print(f"  Error:          {s['error']}", flush=True)
    print("=" * 60, flush=True)


def start_diode_cli() -> bool:
    """Start Diode CLI publishing the configured port. Returns True if started (or already running)."""
    global diode_process, diode_error, _actual_api_port

    with _diode_lock:
        if diode_process is not None and diode_process.poll() is None:
            identity = get_client_identity()
            if identity:
                return True
            try:
                diode_process.terminate()
                diode_process.wait(timeout=2)
            except Exception:
                try:
                    diode_process.kill()
                except Exception:
                    pass
            diode_process = None

    path = find_diode_executable()
    if not path:
        diode_error = "Diode executable not found. Install from https://diode.io/download/#cli"
        print(f"⚠ {diode_error}", flush=True)
        return False

    port_start = get_diode_api_port_start()
    free_port = find_free_port(port_start)
    if not free_port:
        diode_error = f"No free port in range starting at {port_start}"
        print(f"⚠ {diode_error}", flush=True)
        return False

    _actual_api_port = free_port
    DIODE_CLIENT_DIR.mkdir(parents=True, exist_ok=True)
    if not DIODE_LOG_FILE.exists():
        try:
            DIODE_LOG_FILE.touch()
        except Exception:
            pass

    cmd = build_diode_command()
    if not cmd:
        diode_error = "Could not build Diode command"
        print(f"⚠ {diode_error}", flush=True)
        return False

    with _output_lock:
        diode_output.clear()

    stop_tail = threading.Event()

    def tail_log() -> None:
        """Tail DIODE_LOG_FILE and print new lines until stop_tail is set."""
        log_path = DIODE_LOG_FILE
        for _ in range(50):
            if log_path.exists():
                break
            if stop_tail.wait(timeout=0.2):
                return
        if not log_path.exists():
            return
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(0, 2)
                while not stop_tail.wait(timeout=0.25):
                    line = f.readline()
                    if not line:
                        continue
                    stripped = line.rstrip()
                    with _output_lock:
                        diode_output.append(stripped)
                        if len(diode_output) > 500:
                            diode_output.pop(0)
                    if stripped:
                        print(f"  diode | {stripped}", flush=True)
        except Exception:
            pass

    try:
        diode_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        tail_thread = threading.Thread(target=tail_log, daemon=True)
        tail_thread.start()

        print(f"✓ Diode process started (PID {diode_process.pid})", flush=True)

        waited = 0.0
        api_ready = False
        while waited < 15:
            if diode_process.poll() is not None:
                diode_error = "Diode process exited during startup"
                stop_tail.set()
                print("⚠ Diode CLI: process exited during startup.", flush=True)
                _print_recent_diode_output()
                diode_process = None
                return False
            try:
                req = urllib.request.Request(
                    f"{get_actual_api_url()}/config",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=1) as resp:
                    if resp.status == 200:
                        api_ready = True
                        break
            except Exception:
                pass
            time.sleep(0.5)
            waited += 0.5

        if not api_ready:
            diode_error = "Diode API did not become ready in time (check join address and network)"
            print("⚠ Diode CLI: API did not become ready in time (check join address and network).", flush=True)
            stop_tail.set()
            _print_recent_diode_output()
            if diode_process:
                try:
                    diode_process.terminate()
                    diode_process.wait(timeout=2)
                except Exception:
                    try:
                        diode_process.kill()
                    except Exception:
                        pass
                diode_process = None
            return False

        # Poll API for publish state (perimeter bind); see llm-pipeline-demo
        print("Diode Client auto started, waiting for port to be published...", flush=True)
        publish_ready = False
        published_config = None
        publish_waited = 0.0
        while publish_waited < 20:
            if diode_process.poll() is not None:
                diode_error = "Diode process exited"
                stop_tail.set()
                print("⚠ Diode CLI: process exited while waiting for publish.", flush=True)
                _print_recent_diode_output()
                diode_process = None
                return False
            config = _fetch_config()
            if config and _is_port_published_in_config(config):
                publish_ready = True
                published_config = config
                break
            time.sleep(0.5)
            publish_waited += 0.5

        identity = get_client_identity()
        external_port = _external_publish_port_from_config(published_config) if published_config else None
        display_port = external_port if external_port is not None else _publish_port
        if publish_ready and identity:
            print(f"✓ Diode CLI: publishing at {identity}.diode.link:{display_port}", flush=True)
        elif not publish_ready:
            print("⚠ Diode CLI: port not yet published (check perimeter settings).", flush=True)
        print_diode_connection_status()
        if identity and publish_ready:
            urls = get_published_mcp_urls(published_config)
            print("MCP server is published at:", flush=True)
            for u in urls:
                print(f"  {u}", flush=True)
            print("=" * 60 + "\n", flush=True)
        stop_tail.set()
        return True
    except Exception as e:
        diode_error = str(e)
        print(f"⚠ Diode CLI: error starting — {diode_error}", flush=True)
        stop_tail.set()
        _print_recent_diode_output()
        if diode_process:
            try:
                diode_process.terminate()
            except Exception:
                pass
            diode_process = None
        return False


def cleanup_diode() -> None:
    global diode_process
    if diode_process is not None:
        try:
            diode_process.terminate()
            diode_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                diode_process.kill()
            except Exception:
                pass
        except Exception:
            pass
        diode_process = None
