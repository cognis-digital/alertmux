# Demo 04 — Route by owning team with custom rules

## Where the data came from

Four unrelated alerts from three teams, captured in one Alertmanager batch:
a database (`team=database`) Redis replication break, a platform TLS cert
warning, and a data-engineering disk-prediction alert. Each service is
distinct, so each becomes its own incident — the interesting part is **routing**.

`rules.json` is a custom ordered ruleset: the DBA team pages on `error`+, the
data and platform teams get Slack-only, and everything else falls through.

## Run it

```bash
python -m alertmux rules --rules demos/04-team-routing/rules.json
python -m alertmux mux demos/04-team-routing/alerts.json --rules demos/04-team-routing/rules.json
python -m alertmux mux demos/04-team-routing/alerts.json --rules demos/04-team-routing/rules.json --format json | jq '.incidents[] | {key:.correlation_key, receiver, page}'
```

## What to expect

- `sessions` (database, worst=error) -> **pagerduty-dba**, `page=YES`.
- `warehouse` (data, error)          -> **slack-data-eng**, `page=no`.
- `api-gateway` (platform, warning)  -> **slack-platform**, `page=no`.

Rules are evaluated **in order**; the first match wins. Note the DBA rule's
`min_severity: error` means a database `warning` would skip it and hit
`catch-all` — sever-ity gating and label matching combine.

## How to act

Use this file as a starting template for your own `--rules`: copy it, swap the
`team`/`receiver` values for your PagerDuty escalation policies and Slack
channels, and gate `page` on the severities you actually want to be woken for.
