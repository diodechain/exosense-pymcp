"""ExoSense MCP Resources"""

from typing import Dict, Any


def create_resource(uri: str, name: str, description: str) -> Dict[str, Any]:
    """Helper to create a resource"""
    return {
        "uri": uri,
        "name": name,
        "description": description,
        "mimeType": "text/html",
    }


async def load_resource(uri: str, description: str) -> Dict[str, Any]:
    """Load a resource"""
    return {
        "text": f"{description} - Visit {uri} for complete information.",
        "mimeType": "text/plain",
        "uri": uri,
    }


ExosenseOverview = {
    "uri": "https://docs.exosite.io/exosense/overview/",
    "name": "ExoSense Overview",
    "description": "Complete overview of the ExoSense platform, including key concepts, architecture, and capabilities for IoT device management and monitoring.",
    "mimeType": "text/html",
    "load": lambda: load_resource(
        "https://docs.exosite.io/exosense/overview/",
        "ExoSense Overview Documentation - Visit https://docs.exosite.io/exosense/overview/ for complete overview of the ExoSense platform, including key concepts, architecture, and capabilities for IoT device management and monitoring.",
    ),
}

ExosenseTerminology = {
    "uri": "https://docs.exosite.io/exosense/terminology/",
    "name": "ExoSense Terminology",
    "description": "Comprehensive glossary of ExoSense terms and concepts including Assets, Devices, Signals, Groups, and other platform-specific terminology.",
    "mimeType": "text/html",
    "load": lambda: load_resource(
        "https://docs.exosite.io/exosense/terminology/",
        "ExoSense Terminology Documentation - Visit https://docs.exosite.io/exosense/terminology/ for comprehensive glossary of ExoSense terms and concepts including Assets, Devices, Signals, Groups, and other platform-specific terminology.",
    ),
}

ExosenseDigitalAssets = {
    "uri": "https://docs.exosite.io/exosense/digital-assets/assets/",
    "name": "ExoSense Digital Assets",
    "description": "Documentation on ExoSense digital assets, including how to create, manage, and monitor assets in the platform.",
    "mimeType": "text/html",
    "load": lambda: load_resource(
        "https://docs.exosite.io/exosense/digital-assets/assets/",
        "ExoSense Digital Assets Documentation - Visit https://docs.exosite.io/exosense/digital-assets/assets/ for documentation on ExoSense digital assets, including how to create, manage, and monitor assets in the platform.",
    ),
}

ExosenseConditions = {
    "uri": "https://docs.exosite.io/exosense/conditions/",
    "name": "ExoSense Conditions",
    "description": "Documentation on ExoSense Conditions, including how to configure, manage, and use conditions for monitoring and alerting within the platform.",
    "mimeType": "text/html",
    "load": lambda: load_resource(
        "https://docs.exosite.io/exosense/conditions/",
        "ExoSense Conditions Documentation - Visit https://docs.exosite.io/exosense/conditions/ for information on configuring, managing, and using conditions for monitoring and alerting in ExoSense.",
    ),
}

ExosenseDigitalInsights = {
    "uri": "https://docs.exosite.io/exosense/digital-assets/insights/",
    "name": "ExoSense Digital Insights",
    "description": "Documentation on ExoSense Digital Insights, including how to create, configure, and use insights for data analysis and visualization within the platform.",
    "mimeType": "text/html",
    "load": lambda: load_resource(
        "https://docs.exosite.io/exosense/digital-assets/insights/",
        "ExoSense Digital Insights Documentation - Visit https://docs.exosite.io/exosense/digital-assets/insights/ for information on creating, configuring, and using insights for data analysis and visualization in ExoSense.",
    ),
}

InsightsOverview = {
    "uri": "https://docs.exosite.io/insights/overview/",
    "name": "ExoSense Insights Platform Overview",
    "description": "Complete overview of the Insights platform, including core concepts, architecture, and capabilities for advanced data analytics and processing.",
    "mimeType": "text/html",
    "load": lambda: load_resource(
        "https://docs.exosite.io/insights/overview/",
        "ExoSense Insights Platform Overview Documentation - Visit https://docs.exosite.io/insights/overview/ for complete overview of the Insights platform, including core concepts, architecture, and capabilities for advanced data analytics and processing.",
    ),
}

InsightsFunctions = {
    "uri": "https://docs.exosite.io/insights/reference/inline-insight-functions/",
    "name": "ExoSense Insights Inline Functions Reference",
    "description": "Comprehensive reference for Insights inline functions, including syntax, parameters, examples, and use cases for data processing and analysis.",
    "mimeType": "text/html",
    "load": lambda: load_resource(
        "https://docs.exosite.io/insights/reference/inline-insight-functions/",
        "ExoSense Insights Inline Functions Reference - Visit https://docs.exosite.io/insights/reference/inline-insight-functions/ for comprehensive reference on Insights inline functions, including syntax, parameters, examples, and use cases for data processing and analysis.",
    ),
}

ExosenseDataTypes = {
    "uri": "https://docs.exosite.io/schema/data-types/",
    "name": "ExoSense Data Types Schema",
    "description": "Complete documentation of ExoSense data types and units supported by the platform. Covers both generic types (STRING, NUMBER, JSON, BOOLEAN) and unit-originated types with physical measurements (temperature, pressure, electrical, etc.). Includes type primitives, value formats, accepted units, and configuration examples for device channels and asset signals.",
    "mimeType": "text/html",
    "load": lambda: load_resource(
        "https://docs.exosite.io/schema/data-types/",
        "ExoSense Data Types Schema Documentation - Visit https://docs.exosite.io/schema/data-types/ for complete documentation of supported data types including generic types (STRING, NUMBER, JSON, BOOLEAN) and unit-originated types for physical measurements (temperature, pressure, electrical). Covers type primitives, value formats, accepted units, and configuration examples for device channels and asset signals.",
    ),
}

