# CEG5101 CA2 — Part 1

MiniEdit topology and a static-cost Ryu routing controller. Maintained by shumin.

This version covers the topology task and normal-network forwarding. Traffic
monitoring, EMA, source blocking and dynamic link costs belong to later parts.

## Environment

Tested on **Ubuntu 20.04 / Python 3.8**, running in Multipass on an Apple Silicon
Mac (aarch64). Run all commands below **inside Ubuntu**, unless marked Mac.
Mininet needs Linux; the controller and switches run in the same VM.

Use an Ubuntu desktop session to open MiniEdit. An existing XFCE/xrdp desktop is
sufficient. The command-line option below also works over an ordinary VM shell.

### Optional: create an Ubuntu VM on a Mac

If Ubuntu is already installed, skip this section. With Multipass installed,
run these commands in the **Mac terminal**:

```bash
multipass launch 20.04 --name ca2-part1 --cpus 2 --memory 4G --disk 30G
multipass shell ca2-part1
```

To add a desktop for MiniEdit, run inside that Ubuntu shell:

```bash
sudo apt-get update
sudo apt-get install -y xfce4 xfce4-terminal xrdp
printf 'startxfce4\n' > ~/.xsession
sudo passwd ubuntu
sudo adduser xrdp ssl-cert
sudo systemctl enable --now xrdp
sudo systemctl restart xrdp
```

Set an Ubuntu login password when prompted. In another **Mac terminal**, run
`multipass info ca2-part1` to find the VM's IPv4 address. Connect an RDP client
(such as Windows App) to that address on port 3389; log in as `ubuntu` with the
password you just set and select the Xorg session. Open a terminal in that
desktop and continue below. The desktop and network should stay inside the VM.

## 1. Get the code

```bash
git clone https://github.com/MILLOPE/CEG5101_CA2.git
cd CEG5101_CA2
```

For a private repository, use an authenticated Git client or download the ZIP
from GitHub. An SSH key on your Mac is not automatically available in Ubuntu.
You can also clone on the Mac and copy the project into your VM.

## 2. Install dependencies

```bash
bash scripts/setup.sh
```

The script installs Open vSwitch, a Python 3 Mininet build, Tk and a local Ryu
virtual environment at `.venv/`. Ryu 4.34 needs the older packaging/eventlet
versions pinned by this project; keep these pins when following this guide.
Your Ubuntu sudo password may be requested.

If PyPI is slow, select a mirror for this command:

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash scripts/setup.sh
```

This changes only the Python package index; APT and Git still use their own
configured sources. Ubuntu 20.04/Python 3.8 is the lab compatibility target;
the installer stops on other versions rather than assuming the same pins work.

## 3. Start the controller — terminal A

From the project directory:

```bash
bash scripts/run_controller.sh
```

Keep this terminal open. The controller listens on TCP **6653**. Before a topology
starts, `ready=False` is expected. The launcher enables LLDP link discovery with
`--observe-links` and prevents a second copy of this controller from starting.

## 4. Open MiniEdit — terminal B in the Ubuntu desktop

```bash
cd ~/CEG5101_CA2
sudo python3 scripts/open_topology.py
```

Adjust the `cd` path if you cloned elsewhere. The saved topology opens
automatically. Click **Run → Run**, or the **Run** button. The terminal enters
the `mininet>` CLI; the GUI can pause while this CLI is active.

Wait until terminal A shows:

```text
Topology: 6 switches, 11/11 links; ready=True
```

The saved `.mn` file selects OpenFlow 1.3 and a remote controller at
`127.0.0.1:6653`. Red dotted connections are controller associations, not data links.

### Command-line alternative

Use this instead of opening MiniEdit; run only one topology at a time:

```bash
sudo mn --custom topology/ceg_mesh_topo.py --topo meshTopo \
  --controller remote,ip=127.0.0.1,port=6653 \
  --switch ovs,protocols=OpenFlow13 --link tc --mac
```

This uses the same supplied Python topology. MiniEdit is still needed to
demonstrate the assignment's first task.

## 5. Check connectivity and routing

At the `mininet>` prompt, type commands without copying the prompt itself:

```text
pingall
h1 ping -c 5 10.0.0.6
sh ovs-ofctl -O OpenFlow13 dump-flows s1
sh ovs-ofctl -O OpenFlow13 dump-flows s2
sh ovs-ofctl -O OpenFlow13 dump-flows s6
```

Expected: `0% dropped (30/30 received)` for `pingall`.
The normal h1-to-h6 route is:

```text
h1 → s1 → s2 → s6 → h6
          5    14       switch-path cost = 19
```

Terminal A logs the learned source/destination MAC addresses, switch path and
cost. Forwarding rules have priority 100; the priority-0 table-miss rule sends
unknown packets to the controller. In the flow tables, `dl_src`, `dl_dst` and
`actions=output:...` identify the forwarding rule and its outgoing port.

For an automated check, first stop the interactive topology with `exit`.
Leave terminal A running, then run in terminal B:

```bash
sudo python3 tests/check_topology.py
sudo xvfb-run -a python3 tests/check_network.py
```

The first check compares the saved MiniEdit topology with the supplied Python
file, including IPs, DPIDs, ports, bandwidth and delays. The second builds the
actual MiniEdit network, checks all 30 host pairs and sends 10 extra h1-to-h6
pings. It verifies forwarding-counter increases of 10 at s1, s2 and s6, and
zero at the other switches. It then stops its test network.

## 6. Stop and restart

In the Mininet CLI, type `exit`. In MiniEdit, close the window after the network
stops. In terminal A, press **Ctrl+C**.

If a previous crash left interfaces behind, close all old topology windows,
stop their CLI sessions, and then run:

```bash
sudo mn -c
```

Start the controller and topology again. Cleanup removes Mininet networks on
this VM, so use it only after stopping other Mininet experiments.

## Topology and controller

Each host hi has IP `10.0.0.i/24` and attaches to si. There are 6 host links and
11 inter-switch links. All links are 40 Mbps; host links have a 15 ms delay.
Inter-switch delays supply this version's static routing costs:

| Link | Cost / delay (ms) | Link | Cost / delay (ms) |
|---|---:|---|---:|
| s1–s2 | 5 | s2–s3 | 10 |
| s4–s5 | 15 | s5–s6 | 20 |
| s1–s4 | 8 | s2–s5 | 12 |
| s3–s6 | 7 | s1–s5 | 18 |
| s2–s4 | 6 | s2–s6 | 14 |
| s3–s5 | 9 | | |

Access-link delay is configured in Mininet but excluded from the switch-path
cost. These costs match `ceg_mesh_topo.py`; the teacher's separate reference
controller uses a different cost table for some links.

The controller waits for all six switches and both LLDP directions of every
configured link, then waits for one stable discovery cycle. It learns host MAC
locations only at host-facing ports. Known destinations use Dijkstra's
lowest-cost path. Broadcast and unknown destinations flood over a minimum
spanning tree, preventing loops in the mesh. Forwarding rules are cleared when
the discovered topology changes. This Part 1 version pauses forwarding if a
configured link disappears; physical-link failure recovery is not implemented.

## Files

```text
controller/path_controller.py  Static routing, discovery and loop-free flooding
topology/ceg_mesh_topo.py       Supplied topology, unchanged
topology/assignment_mesh.mn    Matching MiniEdit topology
scripts/setup.sh              Ubuntu dependencies and Ryu environment
scripts/run_controller.sh     Start the controller
scripts/open_topology.py      Open the saved topology in MiniEdit
scripts/generate_topology.py  Regenerate the .mn file from the supplied topology
tests/check_topology.py       Check topology fidelity and routing algorithms
tests/check_network.py        Mininet integration and measured-path check
vendor/                      Python 3 MiniEdit and its upstream license
requirements.txt             Ryu dependency pins
results/                     Generated locally; excluded from Git
```

Regenerate the MiniEdit file after editing the Python topology:

```bash
sudo python3 scripts/generate_topology.py
sudo python3 tests/check_topology.py
```

Controller state is written to `results/data/topology_state.json`; controller
logs, learned routes and test evidence are under `results/logs/` and
`results/data/`. A fresh run's state replaces the previous state; logs are local
working files, not a versioned experimental dataset.

## Validation

Verified on the Ubuntu 20.04 aarch64 lab VM: topology comparison passed,
`pingall` returned 30/30, and the 10-packet path check matched s1–s2–s6.
The Ryu requirements also installed in a fresh Python 3.8 virtual environment;
`pip check` passed and `ryu-manager --version` returned 4.34. The complete VM
provisioning sequence has not been tested on a newly created VM.

## Troubleshooting

| Symptom | Check |
|---|---|
| `ready=False` after starting the network | Confirm 6 switches, 11 links, OpenFlow 1.3, controller port 6653 and `--observe-links`. |
| `ModuleNotFoundError: mininet` under Python 3 | Rerun setup; the Ubuntu package alone may provide Python 2 bindings. |
| Tk reports no display | Open a terminal inside the Ubuntu desktop, or use the CLI alternative. Use `xvfb-run` for the automated test only. |
| `RTNETLINK ... File exists` | Stop the old topology and run `sudo mn -c` before restarting. |
| Port 6653 already in use | Stop the controller already using that port. |
| Ryu import/packaging error | Use the project `.venv` and pinned versions; avoid a system-wide Ryu install. |

## Credits

The topology comes from the CEG5101 CA2 course materials. The controller adapts
the provided reference's Dijkstra and spanning-tree approach. MiniEdit retains
its original author credits and license in `vendor/`. This repository contains
the Part 1 lab code only.
