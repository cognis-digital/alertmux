"""ALERTMUX - Alert dedup, correlation, and routing in front of Grafana / PagerDuty.

AIOps-lite: takes a stream of raw alerts (Grafana/Alertmanager-style JSON) and
collapses noise into a small set of actionable, routed incidents.
"""
from .core import (
    Alert,
    Incident,
    RoutingRule,
    Engine,
    load_alerts,
    load_rules,
    DEFAULT_RULES,
)

TOOL_NAME = "alertmux"
TOOL_VERSION = "1.0.0"

__all__ = [
    "Alert",
    "Incident",
    "RoutingRule",
    "Engine",
    "load_alerts",
    "load_rules",
    "DEFAULT_RULES",
    "TOOL_NAME",
    "TOOL_VERSION",
]
