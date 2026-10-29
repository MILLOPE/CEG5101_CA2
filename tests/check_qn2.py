"""Test Qn2 in a separate Mininet network and save the measurements."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time

from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.link import TCLink

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
if os.geteuid() != 0:
    parser.error('Run with sudo python3 tests/check_qn2.py')
output = args.output or ROOT / 'results/qn2' / time.strftime('%Y%m%d-%H%M%S')
output.mkdir(parents=True, exist_ok=False)
if not shutil.which('hping3'):
    parser.error('Install hping3: sudo apt-get install hping3')
# These names and this port belong only to this test.
with socket.socket() as check:
    check.bind(('127.0.0.1', 16653))
bridges = subprocess.check_output(['ovs-vsctl', 'list-br'], text=True).split()
if any('q2s%d' % i in bridges for i in range(1, 7)):
    parser.error('A q2 test network is already running. Stop it before retrying.')

topo = json.loads((ROOT / 'topology/assignment_mesh.mn').read_text())
net = Mininet(topo=None, build=False, controller=None, switch=OVSSwitch, link=TCLink)
nodes = {}
report = {'passed': False, 'flood_duration_seconds': 10,
          'controller_sha256': hashlib.sha256(
              (ROOT / 'controller/path_controller.py').read_bytes()).hexdigest()}
controller = None
attack = None
log_file = (output / 'controller.log').open('w')


def read_log():
    return (output / 'controller.log').read_text()


def flows(name):
    return subprocess.check_output(
        ['ovs-ofctl', '-O', 'OpenFlow13', 'dump-flows', 'q2' + name], text=True)


def counters(text):
    result = {'drop': 0, 'forward': 0}
    for line in text.splitlines():
        if not re.search(r'nw_src=10\.0\.0\.2(?:,| )', line):
            continue
        match = re.search(r'n_packets=(\d+)', line)
        if not match:
            continue
        if 'priority=5000' in line:
            result['drop'] += int(match.group(1))
        elif 'priority=100,' in line:
            result['forward'] += int(match.group(1))
    return result


try:
    env = dict(os.environ, EVENTLET_NO_GREENDNS='yes')
    controller = subprocess.Popen([
        str(ROOT / '.venv/bin/ryu-manager'), '--observe-links',
        '--ofp-tcp-listen-port', '16653', str(ROOT / 'controller/path_controller.py')],
        cwd=ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    deadline = time.time() + 10
    while True:
        try:
            with socket.create_connection(('127.0.0.1', 16653), timeout=0.2):
                break
        except OSError:
            if controller.poll() is not None or time.time() > deadline:
                raise RuntimeError('Controller did not start; see controller.log')
            time.sleep(0.2)
    net.addController('q2c0', controller=RemoteController, ip='127.0.0.1', port=16653)
    for switch in topo['switches']:
        opts = switch['opts']
        name = opts['hostname']
        nodes[name] = net.addSwitch('q2' + name, dpid=opts['dpid'], protocols='OpenFlow13')
    for host in topo['hosts']:
        opts = host['opts']
        name = opts['hostname']
        nodes[name] = net.addHost('q2' + name, ip=opts['ip'])
    for link in topo['links']:
        net.addLink(nodes[link['src']], nodes[link['dest']], **link['opts'])
    net.build()
    net.start()
    deadline = time.time() + 45
    while 'ready=True' not in read_log():
        if controller.poll() is not None or time.time() > deadline:
            raise RuntimeError('Controller did not become ready; see controller.log')
        time.sleep(1)

    print('Building the h2 baseline with 20 normal pings.', flush=True)
    with (output / 'h1-normal.log').open('w') as normal_log:
        normal = nodes['h1'].popen(['ping', '-c', '20', '-W', '2', '10.0.0.6'],
                                   stdout=normal_log, stderr=normal_log)
        report['h2_normal'] = nodes['h2'].cmd('ping -c 20 -W 2 10.0.0.3')
        normal.wait(timeout=10)
    report['h1_normal'] = (output / 'h1-normal.log').read_text()
    assert ' 0% packet loss' in report['h2_normal']
    assert 'Q2 BASELINE: IP=10.0.0.2' in read_log()
    assert 'Q2 BLOCKED:' not in read_log()
    assert ' 0% packet loss' in report['h1_normal']

    print('Sending a 10-second ICMP flood from h2 to h3.', flush=True)
    report['flood_start'] = time.time()
    with (output / 'hping.log').open('w') as attack_log:
        attack = nodes['h2'].popen([
            'timeout', '--signal=INT', '10', 'hping3', '--icmp', '--flood', '10.0.0.3'],
            stdout=attack_log, stderr=attack_log)
    deadline = time.time() + 15
    while 'Q2 BLOCKED: IP=10.0.0.2' not in read_log():
        if time.time() > deadline:
            raise AssertionError('h2 was not blocked within 15 seconds')
        time.sleep(0.1)
    report['block_observed'] = time.time()
    report['detection_observed_seconds'] = report['block_observed'] - report['flood_start']
    report['sender_running_at_block'] = attack.poll() is None
    tables = {s: flows(s) for s in ('s1', 's2', 's3', 's4', 's5', 's6')}
    (output / 'flow_tables.txt').write_text(json.dumps(tables, indent=2) + '\n')
    report['drop_rule_switches'] = [s for s, table in tables.items()
                                  if 'priority=5000' in table and 'nw_src=10.0.0.2' in table]
    start = time.time()
    before = counters(flows('s2'))
    time.sleep(1.5)
    after = counters(flows('s2'))
    report['counter_window_seconds'] = time.time() - start
    report['s2_counter_delta'] = {k: after[k] - before[k] for k in before}
    report['sender_running_after_counter_window'] = attack.poll() is None
    report['h1_during_block'] = nodes['h1'].cmd('ping -c 3 -W 2 10.0.0.6')
    attack.wait(timeout=12)
    report['h2_after_block'] = nodes['h2'].cmd('ping -c 3 -W 1 10.0.0.3')
    report['h3_healthy'] = nodes['h3'].cmd('ping -c 3 -W 2 10.0.0.6')
    report['blocked_sources'] = sorted(set(re.findall(r'Q2 BLOCKED: IP=(\S+)', read_log())))
    assert len(report['drop_rule_switches']) == 6
    assert report['sender_running_at_block'] and report['sender_running_after_counter_window']
    assert report['s2_counter_delta']['drop'] > 0
    assert report['s2_counter_delta']['forward'] == 0
    assert ' 0% packet loss' in report['h1_during_block']
    assert ' 0% packet loss' in report['h3_healthy']
    assert '100% packet loss' in report['h2_after_block']
    assert report['blocked_sources'] == ['10.0.0.2']
    report['passed'] = True
    print('PASS: h2 blocked; h1 and h3 remain connected.', flush=True)
finally:
    if attack is not None and attack.poll() is None:
        attack.terminate()
        attack.wait(timeout=5)
    net.stop()
    if controller is not None:
        controller.terminate()
        try:
            controller.wait(timeout=5)
        except subprocess.TimeoutExpired:
            controller.kill()
            controller.wait()
    log_file.close()
    match = re.search(r'Q2 samples: (.+)', read_log())
    if match and Path(match.group(1)).exists():
        shutil.copyfile(match.group(1), output / 'samples.jsonl')
        report['samples_file'] = 'samples.jsonl'
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Saved:', output, flush=True)
