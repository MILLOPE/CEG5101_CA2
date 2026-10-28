"""Convert the supplied Mininet Topo to MiniEdit JSON without changing links."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "topology"))
from ceg_mesh_topo import MeshTopo

root = Path(__file__).resolve().parents[1] / 'topology'
topo = MeshTopo()
positions = {'s1': (190, 230), 's2': (460, 230), 's3': (730, 230),
             's4': (190, 450), 's5': (460, 450), 's6': (730, 450)}
data = {'version': '2', 'hosts': [], 'switches': [], 'links': [],
        'controllers': [{'x': '930', 'y': '70', 'opts': {
            'hostname': 'c0', 'controllerType': 'remote',
            'controllerProtocol': 'tcp', 'remoteIP': '127.0.0.1',
            'remotePort': 6653}}],
        'application': {'ipBase': '10.0.0.0/24', 'startCLI': '1',
            'terminalType': 'xterm', 'switchType': 'ovs', 'dpctl': '',
            'openFlowVersions': {'ovsOf10': '0', 'ovsOf11': '0',
                                 'ovsOf12': '0', 'ovsOf13': '1'}}}
for name in topo.switches():
    i = int(name[1:])
    x, y = positions[name]
    data['switches'].append({'number': str(i), 'x': str(x), 'y': str(y),
        'opts': {'hostname': name, 'nodeNum': i, 'switchType': 'default',
                 'controllers': ['c0'], 'dpid': topo.nodeInfo(name)['dpid']}})
for name in topo.hosts():
    i = int(name[1:])
    x, y = positions['s' + str(i)]
    y += -110 if i <= 3 else 110
    data['hosts'].append({'number': str(i), 'x': str(x), 'y': str(y),
        'opts': {'hostname': name, 'nodeNum': i, 'sched': 'host',
                 'ip': topo.nodeInfo(name)['ip']}})
for _, _, info in topo.links(withInfo=True):
    src, dst = info['node1'], info['node2']
    opts = {k: info[k] for k in ('bw', 'delay', 'port1', 'port2')}
    data['links'].append({'src': src, 'dest': dst, 'opts': opts})
assert len(data['hosts']) == 6 and len(data['switches']) == 6
assert len(data['links']) == 17
output = root / 'assignment_mesh.mn'
output.write_text(json.dumps(data, indent=2) + '\n')
print('Generated:', output)
print('6 hosts, 6 switches, 17 data links; original IPs, DPIDs, ports, bandwidth and delays retained.')
