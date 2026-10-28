"""Integration check using the actual MiniEdit builder, without GUI interaction."""
import json
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))
import miniedit as editor
from mininet.log import setLogLevel

ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'results/data').mkdir(parents=True, exist_ok=True)
(ROOT / 'results/logs').mkdir(parents=True, exist_ok=True)
setLogLevel('info')
app = editor.MiniEdit()
app.top.withdraw()
editor.tkFileDialog.askopenfile = lambda **kw: open(ROOT / 'topology/assignment_mesh.mn', 'rb')
app.loadTopology()
net = None
report = {'passed': False}
try:
    net = app.build()
    net.start()
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            state = json.loads((ROOT / 'results/data/topology_state.json').read_text())
            if state['ready'] and len(state['links']) == 11:
                break
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(1)
    else:
        raise AssertionError('Topology did not become ready within 45 seconds')
    assert state['switches'] == [1, 2, 3, 4, 5, 6]
    assert state['s1_to_s6'] == [1, 2, 6] and state['s1_to_s6_cost'] == 19
    report['topology'] = state
    report['pingall_loss_percent'] = net.pingAll(timeout='2')
    assert report['pingall_loss_percent'] == 0
    def flows():
        return {s.name: subprocess.check_output(
            ['ovs-ofctl', '-O', 'OpenFlow13', 'dump-flows', s.name], text=True)
            for s in net.switches}
    # OVS datapath counters are refreshed asynchronously. Let them settle.
    time.sleep(2)
    before = flows()
    report['h1_to_h6_ping'] = net['h1'].cmd('ping -c 10 -i 0.2 -W 2 10.0.0.6')
    assert ' 0% packet loss' in report['h1_to_h6_ping']
    time.sleep(2)
    after = flows()
    import re
    def count(text):
        return sum(int(re.search(r'n_packets=(\d+)', line).group(1))
                   for line in text.splitlines()
                   if ('dl_src=' + net['h1'].MAC() + ',') in line and ('dl_dst=' + net['h6'].MAC()) in line)
    deltas = {name: count(after[name]) - count(before[name]) for name in after}
    report['h1_to_h6_flow_counter_increase'] = deltas
    assert deltas == {'s1': 10, 's2': 10, 's3': 0, 's4': 0, 's5': 0, 's6': 10}, deltas
    (ROOT / 'results/logs/normal_flow_tables.txt').write_text(
        '\n'.join(name + '\n' + value for name, value in after.items()))
    report['passed'] = True
    print('\nPASS: six hosts all reachable; h1 -> s1 -> s2 -> s6 -> h6; cost 19.')
    print('Measured per-switch packet counter increases:', deltas)
finally:
    (ROOT / 'results/data/normal_network_test.json').write_text(json.dumps(report, indent=2) + '\n')
    if net:
        net.stop()
    app.top.destroy()
