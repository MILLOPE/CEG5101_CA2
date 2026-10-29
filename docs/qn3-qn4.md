# Qn3 and Qn4 plan

Qn1 and Qn2 are implemented. The steps below are the proposed next changes;
the current controller still uses static costs.

## Assignment checklist

| Question | Required evidence |
|---|---|
| Qn3 | Costs for each inter-switch link respond to traffic rate and anomaly status. |
| Qn4 | Test h2→h3, h2→h6 and h5→h6; record h1→h6 paths, loss and throughput before, during and after each anomaly. Verify source blocking, legitimate connectivity and recovery. |
| Evaluation | Topology screenshot, normalized cost/time, loss/time and throughput/time plots, with an explanation of changes. |

The measurement tools, weights and timing below are implementation choices.
They are not additional assignment requirements.

## 1. Set the base costs

The assignment defines C0 as the original cost in the supplied controller.
That table differs from the delays in the supplied topology. Qn1 currently
uses the topology delays, so its recorded h1-to-h6 cost is 19.

For Qn3, use the reference controller's cost table on the eleven links that
actually exist. Use its default cost of 10 for unlisted links. Ignore table
entries for links absent from the topology. Keep Mininet's configured delays
unchanged: propagation delay and routing cost are separate settings.

With those costs, the expected initial h1-to-h6 path is s1–s2–s6, cost 15.
The direct s5–s6 link costs 10, so h5-to-h6 naturally uses the link requested
by the assignment. Record a new baseline when changing the cost convention;
the existing Qn1 screenshots and Qn2 data belong to the earlier configuration.

## 2. Measure link load

Request OpenFlow port statistics alongside the existing flow statistics.
For each inter-switch port:

```text
TX Mbps = 8 × change in tx_bytes / elapsed seconds / 1,000,000
utilisation = max(TX Mbps in each direction) / 40
```

Use the actual interval and clamp utilisation to 0–1. The first reply sets
counter values. A reset starts a new measurement interval. Host-facing ports
are excluded from link costs. Port TX includes control traffic, so measure
application goodput separately in Qn4.

## 3. Update costs

Start with the assignment's equation and adjustable weights:

```text
C = C0 + 20 × utilisation + 25 × anomaly
```

These weights are initial choices, not assignment constants. When Qn2 detects
a source, mark the links on that source's recorded path before clearing any
forwarding rules. A path observed in the flow tables is better evidence than
assuming the current shortest path was used.

Keep the penalty while ingress drop counters show continuing attack attempts.
Clear it after a short quiet period, initially 10 seconds. A fixed timer from
the first detection could expire during a sustained attack.

Save the measured load, base cost, penalty and final cost for every link.
The normalized value for the report is C/C0.

## 4. Reroute existing traffic

Updating the graph alone will not move packets already handled by OVS rules.
Track active source/destination pairs. When costs change, calculate their new
paths and compare them with the installed paths. Replace affected forwarding
rules while preserving Qn2's separate block cookie.

Install the new downstream rules first, use OpenFlow barriers, then switch
the ingress rule and remove obsolete entries. Record the old path, new path,
cost and timestamp.

## 5. Run the three cases

Keep h1-to-h6 ping and a UDP probe running across each experiment:

| Attack | Required link | What to check |
|---|---|---|
| h2 → h3 | s2–s3 | Cost rises and h2 is blocked; h1 may keep its existing path. |
| h2 → h6 | s2–s6 | Cost rises, h2 is blocked and h1 selects a cheaper alternative. |
| h5 → h6 | s5–s6 | Confirm the direct attack path; check whether h1's route is affected. |

Under the proposed reference costs, s1–s5–s6 is a candidate alternative for
h1-to-h6 when s2–s6 is penalized. Calculate the actual path from each measured
cost snapshot rather than hard-coding it. An unchanged path is valid when the
affected link is outside the cheapest legitimate route.

For each case: collect 20–30 seconds of normal traffic, send a bounded flood
longer than the 5-second polling interval, stop it, and continue measuring
until cost and route recovery. Restart the test network between cases to
clear Qn2's permanent block rules.

## 6. Save the evidence

Use one run directory per case, with timestamps shared across:

- Source rates, EMA decisions and block events.
- Link counters, utilisation and normalized costs.
- Installed paths and matching forwarding-counter changes.
- Ping sequence numbers and replies.
- UDP send/receive sequence numbers and payload bytes.

Plot normalized cost, h1-to-h6 loss and received UDP Mbps against the same
time axis. Mark flood start, block and flood end. Loss must compare packets
sent and received in the same measurement window; goodput is received payload
bytes per second. Include packet counts with percentages.

Choose and report a fixed UDP offered rate. Low-rate UDP measures connectivity
under that load, not maximum throughput. Keep these Qn4 measurements separate
from the small Qn2 ping checks already in the repository.
