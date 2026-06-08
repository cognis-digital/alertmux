# Demo 01 - Database cascade gets collapsed into one page

A noisy 5-minute window from Grafana/Alertmanager: a Postgres primary on the
`payments` service starts flapping. Prometheus re-sends the same `PostgresDown`
alert 4 times, the connection-pool saturates (3 repeats), latency SLO burns, and
a downstream `checkout` service throws 5xx errors. That's **12 raw alert events**
for what is really **one incident**.

## Run it

```bash
python -m alertmux mux demos/01-basic/alerts.json
python -m alertmux mux demos/01-basic/alerts.json --format json
python -m alertmux dedup demos/01-basic/alerts.json
```

## What ALERTMUX does

1. **Dedup** — the 4 identical `PostgresDown` events and 3 `PgPoolSaturated`
   events collapse by fingerprint (alertname + identity labels), so 12 events
   become ~5 distinct alerts.
2. **Correlate** — every alert carrying `service=payments` (and the DB labels)
   groups into a single incident inside the 300s window. The unrelated
   `checkout` 5xx alert becomes its own incident.
3. **Route** — the payments incident is `critical`, so it matches the
   `critical-page` rule and routes to **pagerduty** with `page=YES`. The
   `checkout` warning routes to slack only.

Net effect: **12 events -> 2 incidents -> 1 page** instead of a 12-message
pager storm. The `summary.noise_reduction_pct` field quantifies the savings.
