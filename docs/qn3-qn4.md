# Qn3 and Qn4 plan

## Qn3: dynamic link costs

Read switch port counters to calculate each link's traffic rate. Use the
assignment's equation:

```text
C = C0 + α × (R / Rmax) + β × A
```

Use the reference controller's base costs for C0, and record the chosen
weights. Increase the cost of busy or anomaly-affected links. Save the
measured rates and costs for plotting. The current code uses topology delays
as costs, so record a new baseline when switching to the reference costs.

## Qn4: rerouting and evaluation

Keep a legitimate h1→h6 flow running, then test the three specified cases:

| Attack traffic | Link |
|---|---|
| h2 → h3 | s2–s3 |
| h2 → h6 | s2–s6 |
| h5 → h6 | s5–s6 |

Recalculate paths when costs change and update the affected forwarding rules,
keeping the source-blocking rules. Record h1→h6's path, packet loss and
throughput before, during and after each attack. Check source blocking,
legitimate connectivity, and cost/path recovery after the attack stops.

Plot normalized cost, packet loss (%) and throughput (Mbps) against time.
Explain whether h1→h6 changed path in each case; it may stay on its original
path if that path is still cheapest.

These changes are planned; the current implementation covers Qn1 and Qn2.
