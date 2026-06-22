# Demo 07 — Mixed severity vocabularies get normalized

## Where the data came from

A team that never standardized its alert severities. Some rules emit PagerDuty
language (`sev1`, `page`), some use shorthand (`crit`, `warn`), and one uses
`notice`. This file is also in the **bare list** shape (no `{"alerts": ...}`
wrapper) and uses the top-level `name`/`summary` fields — alertmux accepts all
of these input variants.

## Run it

```bash
python -m alertmux mux demos/07-severity-aliases/alerts.json
python -m alertmux dedup demos/07-severity-aliases/alerts.json --format json
```

## What to expect

alertmux maps every alias onto its four canonical levels before anything else:

| input    | normalized |
|----------|------------|
| `sev1`, `page`, `crit` | `critical` |
| `sev2`, `err`          | `error`    |
| `warn`, `sev3`         | `warning`  |
| `notice`               | `info`     |

All five alerts share `service=payments`, so they correlate into **one
incident** whose severity is the worst normalized member — `critical` — which
pages. Without normalization, `sev1` and `crit` would look like two different
severities and routing would be unpredictable.

## How to act

This is why you can point alertmux at heterogeneous sources (Alertmanager +
Datadog + a homegrown script) without first rewriting everyone's severity
labels. If a value is unknown it safe-defaults to `warning` rather than
dropping the alert.
