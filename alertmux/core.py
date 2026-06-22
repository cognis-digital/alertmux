"""ALERTMUX engine: dedup -> correlate -> route.

Pure standard library. The engine consumes raw alerts and produces incidents.

Pipeline
--------
1. Normalize each raw alert into an Alert (labels, severity, timestamp, status).
2. Dedup: alerts sharing a fingerprint (name + sorted identity labels) collapse
   into one. We keep a count, first/last seen, and track firing/resolved state.
3. Correlate: deduped alerts that share a correlation key (default: the service
   label, falling back to host/instance) within a time window group into a
   single Incident, so a cascading failure becomes one page, not twenty.
4. Route: each incident is matched against ordered routing rules (label
   matchers + severity threshold) to pick a receiver and whether to page.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2, "critical": 3}
IDENTITY_LABELS = ("service", "host", "instance", "job", "namespace", "pod", "region")
CORRELATION_PRIORITY = ("service", "namespace", "host", "instance", "job")


def _parse_ts(value: Any) -> datetime:
    """Parse an ISO-8601 timestamp; default to epoch on failure."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str) and value:
        v = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(v)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _norm_severity(value: Any) -> str:
    s = str(value or "warning").strip().lower()
    aliases = {"crit": "critical", "err": "error", "warn": "warning",
               "page": "critical", "sev1": "critical", "sev2": "error",
               "sev3": "warning", "notice": "info"}
    s = aliases.get(s, s)
    return s if s in SEVERITY_ORDER else "warning"


@dataclass
class Alert:
    name: str
    severity: str
    labels: dict[str, str]
    status: str  # "firing" | "resolved"
    starts_at: datetime
    summary: str = ""

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Alert":
        labels = {str(k): str(v) for k, v in (raw.get("labels") or {}).items()}
        anns = {str(k): str(v) for k, v in (raw.get("annotations") or {}).items()}
        name = (raw.get("name") or labels.get("alertname")
                or raw.get("alertname") or "unnamed")
        sev = _norm_severity(raw.get("severity") or labels.get("severity"))
        status = str(raw.get("status") or "firing").strip().lower()
        if status not in ("firing", "resolved"):
            status = "firing"
        ts = raw.get("startsAt") or raw.get("starts_at") or raw.get("timestamp")
        summary = (anns.get("summary") or anns.get("description")
                   or raw.get("summary") or "")
        labels.setdefault("alertname", name)
        labels["severity"] = sev
        return cls(name=name, severity=sev, labels=labels, status=status,
                   starts_at=_parse_ts(ts), summary=summary)

    def fingerprint(self) -> str:
        ident = {k: self.labels[k] for k in IDENTITY_LABELS if k in self.labels}
        key = self.name + "|" + ",".join(f"{k}={v}" for k, v in sorted(ident.items()))
        return key

    def correlation_key(self) -> str:
        for k in CORRELATION_PRIORITY:
            if self.labels.get(k):
                return f"{k}={self.labels[k]}"
        return f"alert={self.name}"


@dataclass
class RoutingRule:
    name: str
    receiver: str
    match: dict[str, str] = field(default_factory=dict)
    min_severity: str = "info"
    page: bool = False

    def matches(self, incident: "Incident") -> bool:
        if SEVERITY_ORDER[incident.severity] < SEVERITY_ORDER[_norm_severity(self.min_severity)]:
            return False
        for k, v in self.match.items():
            if incident.labels.get(k) != str(v):
                return False
        return True

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "RoutingRule":
        return cls(
            name=str(raw.get("name", "rule")),
            receiver=str(raw.get("receiver", "default")),
            match={str(k): str(v) for k, v in (raw.get("match") or {}).items()},
            min_severity=_norm_severity(raw.get("min_severity", "info")),
            page=bool(raw.get("page", False)),
        )


DEFAULT_RULES: list[RoutingRule] = [
    RoutingRule("critical-page", "pagerduty", {}, "critical", page=True),
    RoutingRule("db-errors", "db-oncall", {"team": "database"}, "error", page=True),
    RoutingRule("errors", "slack-alerts", {}, "error", page=False),
    RoutingRule("catch-all", "slack-noise", {}, "info", page=False),
]


@dataclass
class Incident:
    incident_id: str
    correlation_key: str
    severity: str
    labels: dict[str, str]
    alert_count: int  # number of distinct deduped alerts
    event_count: int  # number of raw alert events collapsed
    firing: int
    resolved: int
    first_seen: datetime
    last_seen: datetime
    alert_names: list[str]
    receiver: str = ""
    rule: str = ""
    page: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "correlation_key": self.correlation_key,
            "severity": self.severity,
            "status": "resolved" if self.firing == 0 else "firing",
            "alert_count": self.alert_count,
            "event_count": self.event_count,
            "firing": self.firing,
            "resolved": self.resolved,
            "alert_names": self.alert_names,
            "labels": self.labels,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "receiver": self.receiver,
            "rule": self.rule,
            "page": self.page,
            "summary": self.summary,
        }


@dataclass
class _Dedup:
    alert: Alert
    count: int
    firing: int
    resolved: int
    first_seen: datetime
    last_seen: datetime


class Engine:
    def __init__(self, rules: list[RoutingRule] | None = None,
                 correlation_window_sec: int = 300):
        self.rules = rules if rules is not None else list(DEFAULT_RULES)
        self.correlation_window_sec = correlation_window_sec

    def dedup(self, alerts: Iterable[Alert]) -> dict[str, _Dedup]:
        buckets: dict[str, _Dedup] = {}
        for a in alerts:
            fp = a.fingerprint()
            d = buckets.get(fp)
            if d is None:
                buckets[fp] = _Dedup(
                    alert=a, count=1,
                    firing=1 if a.status == "firing" else 0,
                    resolved=1 if a.status == "resolved" else 0,
                    first_seen=a.starts_at, last_seen=a.starts_at,
                )
            else:
                d.count += 1
                if a.status == "firing":
                    d.firing += 1
                else:
                    d.resolved += 1
                d.first_seen = min(d.first_seen, a.starts_at)
                if a.starts_at >= d.last_seen:
                    d.last_seen = a.starts_at
                    d.alert = a  # newest representative
                if SEVERITY_ORDER[a.severity] > SEVERITY_ORDER[d.alert.severity]:
                    d.alert = a
        return buckets

    def correlate(self, deduped: dict[str, _Dedup]) -> list[Incident]:
        # group by correlation key, then split groups whose events span > window
        groups: dict[str, list[_Dedup]] = {}
        for d in deduped.values():
            groups.setdefault(d.alert.correlation_key(), []).append(d)

        incidents: list[Incident] = []
        for ckey, members in groups.items():
            members.sort(key=lambda m: m.first_seen)
            window = []
            window_start: datetime | None = None
            for m in members:
                if window_start is None:
                    window, window_start = [m], m.first_seen
                elif (m.first_seen - window_start).total_seconds() <= self.correlation_window_sec:
                    window.append(m)
                else:
                    incidents.append(self._build_incident(ckey, window, len(incidents)))
                    window, window_start = [m], m.first_seen
            if window:
                incidents.append(self._build_incident(ckey, window, len(incidents)))
        incidents.sort(key=lambda i: (-SEVERITY_ORDER[i.severity], i.first_seen))
        return incidents

    def _build_incident(self, ckey: str, members: list[_Dedup], idx: int) -> Incident:
        worst = max(members, key=lambda m: SEVERITY_ORDER[m.alert.severity])
        first = min(m.first_seen for m in members)
        last = max(m.last_seen for m in members)
        firing = sum(m.firing for m in members)
        resolved = sum(m.resolved for m in members)
        events = sum(m.count for m in members)
        names = sorted({m.alert.name for m in members})
        labels = dict(worst.alert.labels)
        # shared labels across members are the trustworthy incident labels
        common = dict(members[0].alert.labels)
        for m in members[1:]:
            common = {k: v for k, v in common.items() if m.alert.labels.get(k) == v}
        labels.update(common)
        iid = f"INC-{abs(hash((ckey, first.isoformat()))) % 100000:05d}"
        return Incident(
            incident_id=iid, correlation_key=ckey, severity=worst.alert.severity,
            labels=labels, alert_count=len(members), event_count=events,
            firing=firing, resolved=resolved, first_seen=first, last_seen=last,
            alert_names=names, summary=worst.alert.summary,
        )

    def route(self, incident: Incident) -> Incident:
        for rule in self.rules:
            if rule.matches(incident):
                incident.receiver = rule.receiver
                incident.rule = rule.name
                incident.page = rule.page
                return incident
        incident.receiver = "unrouted"
        incident.rule = "none"
        incident.page = False
        return incident

    def process(self, alerts: Iterable[Alert]) -> list[Incident]:
        deduped = self.dedup(alerts)
        incidents = self.correlate(deduped)
        for inc in incidents:
            self.route(inc)
        return incidents


def load_alerts(raw: Any) -> list[Alert]:
    """Accept a list of alerts, an Alertmanager webhook ({"alerts": [...]}),
    or a single alert dict."""
    if isinstance(raw, dict):
        if isinstance(raw.get("alerts"), list):
            raw = raw["alerts"]
        else:
            raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("alert input must be a list, an object, or an Alertmanager webhook")
    return [Alert.from_raw(r) for r in raw if isinstance(r, dict)]


def load_rules(raw: Any) -> list[RoutingRule]:
    if isinstance(raw, dict) and isinstance(raw.get("rules"), list):
        raw = raw["rules"]
    if not isinstance(raw, list):
        raise ValueError("rules input must be a list or an object with a 'rules' list")
    return [RoutingRule.from_raw(r) for r in raw if isinstance(r, dict)]


# --- SARIF 2.1.0 export -------------------------------------------------------
# Map alertmux severities onto SARIF result levels. SARIF only has
# error/warning/note/none, so error+critical -> "error".
_SARIF_LEVEL = {"critical": "error", "error": "error",
                "warning": "warning", "info": "note"}
# SARIF security-severity is a 0.0-10.0 string (CVSS-like) used by GitHub
# code-scanning to bucket results.
_SARIF_SECURITY_SEVERITY = {"critical": "9.0", "error": "7.0",
                            "warning": "4.0", "info": "1.0"}


def to_sarif(incidents: list["Incident"],
             tool_name: str = "alertmux",
             tool_version: str = "0.0.0") -> dict[str, Any]:
    """Render incidents as a SARIF 2.1.0 log.

    Each incident becomes one SARIF `result`; each distinct alert name that
    fed the incident is registered once as a reporting-descriptor `rule`. The
    incident's correlation key is surfaced as the result's logical location so
    a code-scanning UI can group by service/host. Output validates against the
    OASIS SARIF 2.1.0 schema.
    """
    rules_index: dict[str, int] = {}
    sarif_rules: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for inc in incidents:
        for name in inc.alert_names:
            if name not in rules_index:
                rules_index[name] = len(sarif_rules)
                sarif_rules.append({
                    "id": name,
                    "name": name,
                    "shortDescription": {"text": name},
                    "defaultConfiguration": {
                        "level": _SARIF_LEVEL.get(inc.severity, "warning")},
                })
        primary = inc.alert_names[0] if inc.alert_names else "incident"
        msg = inc.summary or (f"{inc.alert_count} alert(s) correlated on "
                              f"{inc.correlation_key} "
                              f"({inc.event_count} raw events)")
        properties = {
            "incident_id": inc.incident_id,
            "correlation_key": inc.correlation_key,
            "status": "resolved" if inc.firing == 0 else "firing",
            "alert_count": inc.alert_count,
            "event_count": inc.event_count,
            "firing": inc.firing,
            "resolved": inc.resolved,
            "receiver": inc.receiver,
            "rule": inc.rule,
            "page": inc.page,
            "first_seen": inc.first_seen.isoformat(),
            "last_seen": inc.last_seen.isoformat(),
            "security-severity": _SARIF_SECURITY_SEVERITY.get(inc.severity, "0.0"),
        }
        results.append({
            "ruleId": primary,
            "ruleIndex": rules_index.get(primary, 0),
            "level": _SARIF_LEVEL.get(inc.severity, "warning"),
            "message": {"text": msg},
            "partialFingerprints": {"alertmuxIncidentId": inc.incident_id},
            "locations": [{
                "logicalLocations": [{
                    "name": inc.correlation_key,
                    "kind": "namespace",
                }],
            }],
            "properties": properties,
        })

    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{
            "tool": {"driver": {
                "name": tool_name,
                "version": tool_version,
                "informationUri": "https://github.com/cognis-digital/alertmux",
                "rules": sarif_rules,
            }},
            "results": results,
        }],
    }
