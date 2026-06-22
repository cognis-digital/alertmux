# Demo 06 — Export incidents as SARIF 2.1.0 for CI / code-scanning

## Where the data came from

A synthetic-monitoring batch: the always-on `DeadMansSwitch` heartbeat, a
failing blackbox probe against the `checkout` healthz endpoint, and a cert
warning. This demo is about the **output format**, not the correlation.

## Run it

```bash
python -m alertmux mux demos/06-sarif-ci/alerts.json --format sarif
python -m alertmux mux demos/06-sarif-ci/alerts.json --format sarif > alertmux.sarif
```

## What to expect

A valid **SARIF 2.1.0** log:

- `runs[0].tool.driver.rules` — one reporting descriptor per distinct
  alertname, with a default level.
- `runs[0].results` — one result per incident. Each carries:
  - `level` (`error` for critical/error, `warning`, `note` for info),
  - `properties["security-severity"]` (0.0–10.0, how GitHub buckets it),
  - `partialFingerprints.alertmuxIncidentId` so re-runs deduplicate in the UI,
  - a `logicalLocations` entry naming the correlation key (service/host).

## How to act

Upload the file in a GitHub Actions workflow so incidents show up in the
**Security → Code scanning** tab, deduplicated across runs by fingerprint:

```yaml
- run: alertmux mux alerts.json --format sarif > alertmux.sarif
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: alertmux.sarif
```

Any SARIF-aware viewer (VS Code SARIF Explorer, Azure DevOps, GitLab) ingests
the same file — no alertmux-specific plugin required.
