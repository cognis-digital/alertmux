# Demo 08 — Stream alerts from stdin and gate a pipeline on the result

## Where the data came from

A Kafka broker (`kafka-3`) backing the `events-bus` service goes under-replicated
and consumer lag balloons. In a real pipeline these alerts arrive as a JSON body
on stdin — e.g. piped from `curl` against the Alertmanager API, or from a
message-queue consumer — not from a file on disk.

## Run it

```bash
# pipe a file in (use - to read stdin)
cat demos/08-stdin-pipeline/alerts.json | python -m alertmux dedup -

# full pipeline from stdin, machine-readable
cat demos/08-stdin-pipeline/alerts.json | python -m alertmux mux - --format json

# CI gate: read the noise-reduction number with jq
cat demos/08-stdin-pipeline/alerts.json \
  | python -m alertmux mux - --format json \
  | jq '.summary.noise_reduction_pct'

# does anything page? (1 = yes -> fail the job)
cat demos/08-stdin-pipeline/alerts.json \
  | python -m alertmux mux - --format json \
  | jq -e '.summary.paging == 0'
```

## What to expect

Four events collapse to two deduped alerts, then one incident on
`service=events-bus`. Worst severity is `error`, so it routes to
`slack-alerts` with `page=no` and `summary.paging` is `0` — the `jq -e` gate
above exits `0` (success).

## How to act

Wire `alertmux mux - --format json | jq -e '.summary.paging == 0'` into a
synthetic/canary job: if a deploy starts producing page-worthy incidents, the
non-zero exit fails the pipeline before the rollout proceeds. The `-` argument
is the convention for "read from stdin" across all subcommands.
