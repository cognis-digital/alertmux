"""ALERTMUX command-line interface.

Subcommands
-----------
  mux      Full pipeline: dedup + correlate + route raw alerts into incidents.
  dedup    Show dedup buckets only (noise-reduction view).
  rules    Print the active routing rules.

Examples
--------
  python -m alertmux mux demos/01-basic/alerts.json
  python -m alertmux mux alerts.json --rules rules.json --format json
  cat alerts.json | python -m alertmux dedup -
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import TOOL_NAME, TOOL_VERSION
from .core import Engine, load_alerts, load_rules, DEFAULT_RULES, to_sarif


def _read(path: str) -> Any:
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    return json.loads(text)


def _print(obj: Any, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(obj, indent=2, default=str))
        return
    _print_table(obj)


def _print_table(obj: Any) -> None:
    if isinstance(obj, dict) and "incidents" in obj:
        s = obj["summary"]
        print(f"events={s['events']}  alerts={s['unique_alerts']}  "
              f"incidents={s['incidents']}  paging={s['paging']}  "
              f"noise_reduction={s['noise_reduction_pct']}%")
        print("-" * 84)
        hdr = f"{'INCIDENT':<10} {'SEV':<8} {'STAT':<8} {'EVTS':>4} {'RECEIVER':<14} PAGE  KEY"
        print(hdr)
        print("-" * 84)
        for inc in obj["incidents"]:
            print(f"{inc['incident_id']:<10} {inc['severity']:<8} "
                  f"{inc['status']:<8} {inc['event_count']:>4} "
                  f"{inc['receiver']:<14} {'YES ' if inc['page'] else 'no  '} "
                  f"{inc['correlation_key']}")
            print(f"           names={','.join(inc['alert_names'])}")
    elif isinstance(obj, dict) and "buckets" in obj:
        print(f"{'COUNT':>5}  {'SEV':<8} {'FINGERPRINT'}")
        print("-" * 60)
        for b in obj["buckets"]:
            print(f"{b['count']:>5}  {b['severity']:<8} {b['fingerprint']}")
    elif isinstance(obj, dict) and "rules" in obj:
        for r in obj["rules"]:
            print(f"{r['name']:<16} -> {r['receiver']:<14} "
                  f"min_sev={r['min_severity']:<8} page={r['page']} match={r['match']}")
    else:
        print(json.dumps(obj, indent=2, default=str))


def _build_engine(args: argparse.Namespace) -> Engine:
    rules = load_rules(_read(args.rules)) if getattr(args, "rules", None) else list(DEFAULT_RULES)
    return Engine(rules=rules, correlation_window_sec=args.window)


def _cmd_mux(args: argparse.Namespace) -> int:
    engine = _build_engine(args)
    alerts = load_alerts(_read(args.input))
    incidents = engine.process(alerts)
    events = sum(1 for _ in alerts)
    paging = sum(1 for i in incidents if i.page)
    reduction = round((1 - len(incidents) / events) * 100, 1) if events else 0.0
    if args.format == "sarif":
        print(json.dumps(to_sarif(incidents, TOOL_NAME, TOOL_VERSION),
                         indent=2, default=str))
        return 0
    out = {
        "summary": {
            "events": events,
            "unique_alerts": len(engine.dedup(alerts)),
            "incidents": len(incidents),
            "paging": paging,
            "noise_reduction_pct": reduction,
        },
        "incidents": [i.to_dict() for i in incidents],
    }
    _print(out, args.format)
    return 0


def _cmd_dedup(args: argparse.Namespace) -> int:
    engine = Engine(correlation_window_sec=args.window)
    alerts = load_alerts(_read(args.input))
    buckets = engine.dedup(alerts)
    items = [{
        "fingerprint": fp,
        "count": d.count,
        "severity": d.alert.severity,
        "firing": d.firing,
        "resolved": d.resolved,
    } for fp, d in sorted(buckets.items(), key=lambda kv: -kv[1].count)]
    _print({"buckets": items, "unique": len(items),
            "events": sum(b["count"] for b in items)}, args.format)
    return 0


def _cmd_rules(args: argparse.Namespace) -> int:
    rules = load_rules(_read(args.rules)) if getattr(args, "rules", None) else list(DEFAULT_RULES)
    out = {"rules": [{"name": r.name, "receiver": r.receiver, "match": r.match,
                      "min_severity": r.min_severity, "page": r.page} for r in rules]}
    _print(out, args.format)
    return 0


_FORMATS = ["table", "json", "sarif"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=TOOL_NAME,
                                description="Alert dedup, correlation, and routing (AIOps-lite).")
    p.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    p.add_argument("--format", choices=_FORMATS, default="table")
    sub = p.add_subparsers(dest="command", required=True)

    # --format is accepted both before AND after the subcommand. The
    # subcommand-level copy uses SUPPRESS as its default so that omitting it
    # leaves the global value intact rather than resetting it to "table".
    def add_format(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--format", choices=_FORMATS, default=argparse.SUPPRESS,
                            dest="format", help="output format (table|json|sarif)")

    m = sub.add_parser("mux", help="dedup + correlate + route into incidents")
    m.add_argument("input", help="alerts JSON file, or - for stdin")
    m.add_argument("--rules", help="routing rules JSON file (defaults built in)")
    m.add_argument("--window", type=int, default=300, help="correlation window seconds")
    add_format(m)
    m.set_defaults(func=_cmd_mux)

    d = sub.add_parser("dedup", help="show dedup buckets only")
    d.add_argument("input", help="alerts JSON file, or - for stdin")
    d.add_argument("--window", type=int, default=300)
    add_format(d)
    d.set_defaults(func=_cmd_dedup)

    r = sub.add_parser("rules", help="print active routing rules")
    r.add_argument("--rules", help="routing rules JSON file (defaults built in)")
    add_format(r)
    r.set_defaults(func=_cmd_rules)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
