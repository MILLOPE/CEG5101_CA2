"""Check the MiniEdit export against the supplied topology and routing code."""
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'topology'))
from ceg_mesh_topo import MeshTopo

topo = MeshTopo()
data = json.loads((ROOT / 'topology/assignment_mesh.mn').read_text())
assert {h['opts']['hostname']: h['opts']['ip'] for h in data['hosts']} == {
    h: topo.nodeInfo(h)['ip'] for h in topo.hosts()}
assert {s['opts']['hostname']: s['opts']['dpid'] for s in data['switches']} == {
    s: topo.nodeInfo(s)['dpid'] for s in topo.switches()}
expected = {}
for _, _, info in topo.links(withInfo=True):
    expected[info['node1'], info['node2']] = {
        k: info[k] for k in ('bw', 'delay', 'port1', 'port2')}
assert {(l['src'], l['dest']): l['opts'] for l in data['links']} == expected
assert len(data['hosts']) == len(data['switches']) == 6 and len(expected) == 17

# Load the actual pure functions without importing Ryu into system Python.
code = ast.parse((ROOT / 'controller/path_controller.py').read_text())
functions = [n for n in code.body if isinstance(n, ast.FunctionDef)
             and n.name in ('shortest_path', 'spanning_tree')]
import heapq
scope = {'heapq': heapq}
exec(compile(ast.Module(body=functions, type_ignores=[]), '<routing>', 'exec'), scope)
graph = {i: {} for i in range(1, 7)}
for (u, v), opts in expected.items():
    if u.startswith('s') and v.startswith('s'):
        a, b = int(u[1:]), int(v[1:])
        graph[a][b] = graph[b][a] = float(opts['delay'][:-2])
assert scope['shortest_path'](graph, 1, 6) == ([1, 2, 6], 19)
assert scope['shortest_path'](graph, 6, 1) == ([6, 2, 1], 19)
assert scope['shortest_path']({1: {}, 2: {}}, 1, 2) == ([], float('inf'))
tree = scope['spanning_tree'](graph)
assert len(tree) == 5
assert sum(graph[u][v] for u, v in tree) == 37
print('PASS: original topology preserved; Dijkstra path cost 19; MST cost 37.')
