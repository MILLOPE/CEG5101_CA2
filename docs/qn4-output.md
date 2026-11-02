# Qn4 command-line results

Selected output from the saved h2→h6 experiment. The attacking source was
h2; h1→h6 TCP traffic and ICMP probes ran throughout the test.

## Detection and blocking

From `controller.log`:

```text
Q2 ANOMALY: IP=10.0.0.2 rate=34466.60 pps baseline=0.74 pps
Q3: Anomaly penalty applied to links [(2, 6)] for 30 seconds
Q2 BLOCKED: IP=10.0.0.2 switches=6
Q3: Anomaly penalty expired on s2-s6
```

The source IP is blocked on six switches. The 30-second penalty affects
routing costs; the IP block remains after that penalty is cleared.

The matching rule on s2, showing its match and action fields:

```text
priority=5000,ip,nw_src=10.0.0.2 actions=drop
```

## Connectivity

The h1→h6 ping summary:

```text
100 packets transmitted, 99 received, 1% packet loss, time 100327ms
```

The attacking h2 host tried to ping h6 after blocking:

```text
3 packets transmitted, 0 received, 100% packet loss, time 2076ms
```

## Run summary

The analysis prints this summary and saves it as `analysis-output.txt` in
the result directory:

```text
PASS h2-h6
Source 10.0.0.2: drop rules on 6/6 switches
Flood check (2.18 s): drop +119701, forward +0
TCP paths: s1-s2-s6 / s1-s5-s6 / s1-s2-s6
ICMP probes: 99/100 replies, 1.0% loss
Receiver Mbps (before / during / after): 37.77 / 29.00 / 38.17
Lowest 5-second receiver rate: 0.0023 Mbps
Sampled path cost: 89.86 -> 20.00
```

`drop +119701, forward +0` is the measured counter change while the flood
was still running. Receiver rates are phase averages. The 0.0023 Mbps value
is a separate 5-second interval, so the temporary drop remains visible.

The figure and these excerpts use recorded data. Fresh runs will have
different rates, counts and timings.
