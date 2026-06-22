# Demo 03 — A flapping target: 8 events that should never page anyone

## Where the data came from

A node-exporter (`exporter-2:9100`) on a non-critical `ad-clicks` host with a
marginal NIC. Overnight it flaps: `TargetDown` fires and resolves four times in
five minutes — classic flapping noise that, raw, would spam an on-call channel
with eight messages.

## Run it

```bash
python -m alertmux dedup demos/03-flapping-resolved/alerts.json
python -m alertmux mux demos/03-flapping-resolved/alerts.json
```

## What to expect

`dedup` collapses all 8 events into **one fingerprint** (same alertname +
identity labels) with `firing=4 resolved=4`. `mux` produces **one incident**.
Because the worst severity is only `warning`, it does **not** match
`critical-page` or the `error` rule — it falls to `slack-noise` with
`page=no`. `noise_reduction_pct` ≈ 87%.

## How to act

No page — exactly right. The single incident with a 4/4 firing/resolved split
is the signature of flapping. Action is a daytime ticket: replace the NIC or add
a `for: 10m` clause to the rule, not a 2 a.m. wake-up.
