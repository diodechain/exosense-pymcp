#!/usr/bin/env bash
# Build a Diode deploy tarball ({UUID}.tar.gz). Does NOT include .env — too sensitive.
# Configure the same variables in your Diode Deploy project so the container gets them as env.
# Usage: from repo root, with DIODE_MCP_DEPLOY_UUID in .env (for UUID only) or pass UUID:
#   ./scripts/diode_deploy_bundle.sh
# Or: ./scripts/diode_deploy_bundle.sh <uuid>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UUID="${DIODE_MCP_DEPLOY_UUID:-${1:-}}"
if [ -z "${UUID}" ] && [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  UUID="${DIODE_MCP_DEPLOY_UUID:-}"
fi
if [ -z "${UUID}" ]; then
  echo "Set DIODE_MCP_DEPLOY_UUID in .env, export it, or pass the UUID as the first argument." >&2
  exit 1
fi

OUT="/tmp/${UUID}.tar.gz"
tar -czf "${OUT}" \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='diode_client/*.db' \
  --exclude='diode_client/*.log' \
  --exclude='.cursor' \
  --exclude='.env' \
  -C "${ROOT}" .

echo "Wrote ${OUT} (does not include .env — set env in Diode Deploy project)"
echo "Upload example (set peer from DIODE_MCP_DEPLOY_TARGET):"
echo "  diode push ${OUT} 0x....diode:30000:${UUID}.tar.gz"
