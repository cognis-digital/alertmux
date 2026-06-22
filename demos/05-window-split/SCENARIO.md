# Demo 05 — Same service, two outages 11 hours apart = two incidents

## Where the data came from

The `search` service had a rough day: a brief error spike during the 08:05
morning deploy — then an *unrelated* critical 5xx storm at the 19:40 evening
traffic peak. All four alerts share `service=search`, so a naive "group by
service" would smear them into one misleading mega-incident spanning the whole
day.

## Run it

```bash
python -m alertmux mux demos/05-window-split/alerts.json
# tighten or widen the correlation window:
python -m alertmux mux demos/05-window-split/alerts.json --window 600
python -m alertmux mux demos/05-window-split/alerts.json --window 86400
```

## What to expect

With the default `--window 300` (5 min), the morning cluster and the evening
cluster are **>11h apart**, so alertmux splits them into **two incidents** on
the same correlation key:

- morning incident: worst severity `error`.
- evening incident: worst severity `critical` -> pages.

Widen to `--window 86400` (one day) and they collapse into a single incident —
demonstrating that the time window, not just the label, defines an incident.

## How to act

The split keeps your post-incident review honest: two MTTR clocks, two
root-cause threads. Tune `--window` to your service's natural recovery time —
too wide hides distinct outages, too narrow re-fragments one event.
