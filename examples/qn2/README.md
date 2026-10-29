# Qn2 example run

Recorded in the Ubuntu 20.04 aarch64 lab VM with `tests/check_qn2.py`.
`result.json` contains the measured checks and timing. `samples.jsonl` contains
actual controller samples; `controller.log` contains the matching text log.
The controller file's SHA-256 is recorded in the result.

The test used separate bridge names q2s1–q2s6 and controller port 16653.
Source IPs, switch DPIDs, links, ports, bandwidth and delays match the supplied
topology. The ICMP flood was limited to 10 seconds inside that network.

Reproduce the figures from the repository root:

```bash
.venv/bin/python tools/plot_qn2.py examples/qn2/result.json
```

This is a single Qn2 run. It contains no dynamic link costs or Qn4 throughput
measurements.
