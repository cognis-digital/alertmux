# Demo 02 — A single bad K8s node fans out into five alerts

## Where the data came from

A Prometheus + Alertmanager stack monitoring an EKS cluster in `us-east-1`.
One worker node (`ip-10-0-3-14`) runs out of memory. Within ~60 seconds the
`kube-prometheus-stack` rules fire a cascade: the node flips `NotReady`, raises
`MemoryPressure`, a `kube-proxy` pod starts crash-looping, and the kubelet trips
its pod-count ceiling. Six raw events, one root cause.

This file is in the standard **Alertmanager webhook** shape (`{"alerts": [...]}`)
with the labels `kube-prometheus-stack` actually emits (`node`, `namespace`,
`pod`, `region`).

## Run it

```bash
python -m alertmux mux demos/02-k8s-node-pressure/alerts.json
python -m alertmux mux demos/02-k8s-node-pressure/alerts.json --format json
```

## What to expect

All six events share `namespace=kube-system`, so they correlate into **one
incident** inside the default 300s window. The worst member is `critical`
(`KubeNodeNotReady`), so the incident routes to **pagerduty** with `page=YES`.
The trailing `resolved` event is counted, but because firing alerts remain the
incident status stays `firing`. You should see `noise_reduction_pct` ≈ 83%.

## How to act

Page goes to the on-call. The single incident already names every symptom
(`alert_names`), so the responder immediately sees node + memory + crash-loop
correlate — cordon/drain `ip-10-0-3-14` rather than chasing five tickets.
