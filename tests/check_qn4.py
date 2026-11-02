"""Run one Qn4 case with continuous h1-to-h6 TCP traffic and ping probes."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--case', choices=['h2-h3', 'h2-h6', 'h5-h6'], default='h2-h6')
parser.add_argument('--output', type=Path)
args = parser.parse_args()
source, destination = args.case.split('-')
source_ip, destination_ip = '10.0.0.' + source[1:], '10.0.0.' + destination[1:]
if os.geteuid() != 0:
    parser.error('Run with sudo python3 tests/check_qn4.py')
out = (args.output or ROOT / 'results/qn4' / (time.strftime('%Y%m%d-%H%M%S') + '-' + args.case)).resolve()
out.mkdir(parents=True, exist_ok=False)
topo = json.loads((ROOT / 'topology/assignment_mesh.mn').read_text())
previous_files = set((ROOT / 'results/data').glob('qn[23]-*.jsonl'))
net = Mininet(topo=None, build=False, controller=None, switch=OVSSwitch, link=TCLink)
nodes, ports = {}, {}
processes, logs = [], []
controller = None
report = {'passed': False, 'case': args.case, 'tcp_seconds': 90, 'flood_seconds': 10}


def start(host, command, filename):
    log = (out / filename).open('w')
    logs.append(log)
    process = nodes[host].popen(command, stdout=log, stderr=subprocess.STDOUT,
                                env=dict(os.environ, TZ='UTC'))
    processes.append(process)
    return process


def controller_log():
    return (out / 'controller.log').read_text()


def tables():
    return {i: subprocess.check_output(['ovs-ofctl', '-O', 'OpenFlow13', 'dump-flows', 'q4s%d' % i], text=True)
            for i in range(1, 7)}


def flow_path(current, source=1, destination=6, protocol='tcp'):
    switch, incoming, path = source, 1, [source]
    while len(path) <= 6:
        rules = [line for line in current[switch].splitlines()
                 if 'priority=100,' + protocol + ',' in line
                 and 'in_port=%d,' % incoming in line
                 and 'nw_src=10.0.0.%d,' % source in line
                 and re.search(r'nw_dst=10\.0\.0\.%d(?:,| )' % destination, line)]
        if not rules:
            return []
        outgoing = int(re.search(r'actions=output:(\d+)', rules[0]).group(1))
        if switch == destination and outgoing == 1:
            return path
        if (switch, outgoing) not in ports:
            return []
        switch, incoming = ports[switch, outgoing]
        path.append(switch)
    return []


def source_counters(table):
    result = {'drop': 0, 'forward': 0}
    for line in table.splitlines():
        if not re.search(r'nw_src=' + re.escape(source_ip) + r'(?:,| )', line):
            continue
        count = re.search(r'n_packets=(\d+)', line)
        if count:
            result['drop' if 'priority=5000,' in line else 'forward'] += int(count[1])
    return result


try:
    log = (out / 'controller.log').open('w')
    logs.append(log)
    controller = subprocess.Popen([
        str(ROOT / '.venv/bin/ryu-manager'), '--observe-links', '--ofp-tcp-listen-port', '16653',
        str(ROOT / 'controller/path_controller.py')], cwd=ROOT,
        env=dict(os.environ, EVENTLET_NO_GREENDNS='yes'), stdout=log, stderr=subprocess.STDOUT)
    net.addController('q4c0', controller=RemoteController, ip='127.0.0.1', port=16653)
    for item in topo['switches']:
        opts = item['opts']
        nodes[opts['hostname']] = net.addSwitch('q4' + opts['hostname'], dpid=opts['dpid'], protocols='OpenFlow13')
    for item in topo['hosts']:
        opts = item['opts']
        nodes[opts['hostname']] = net.addHost('q4' + opts['hostname'], ip=opts['ip'], mac='00:00:00:00:00:0' + opts['hostname'][1:])
    for link in topo['links']:
        net.addLink(nodes[link['src']], nodes[link['dest']], **link['opts'])
        if link['src'].startswith('s') and link['dest'].startswith('s'):
            u, v = int(link['src'][1:]), int(link['dest'][1:])
            p1, p2 = link['opts']['port1'], link['opts']['port2']
            ports[u, p1], ports[v, p2] = (v, p2), (u, p1)
    net.build()
    net.start()
    deadline = time.time() + 50
    while 'ready=True' not in controller_log():
        if controller.poll() is not None or time.time() > deadline:
            raise RuntimeError('Controller did not become ready')
        time.sleep(1)
    report['pingall_loss_percent'] = net.pingAll(timeout='1')
    # Establish the attack source's ICMP path before the TCP load changes costs.
    baseline = start(source, ['ping', '-c', '20', '-W', '2', destination_ip], 'source-baseline.log')
    capture = start('h1', ['tcpdump', '-U', '-n', '-s', '128', '-i', 'q4h1-eth0', '-w', str(out / 'h1-icmp.pcap'),
                            'icmp and host 10.0.0.1 and host 10.0.0.6'], 'tcpdump.log')
    time.sleep(.5)
    ping = start('h1', ['ping', '-D', '-c', '100', '-i', '1', '-W', '2', '10.0.0.6'], 'h1-ping.log')
    server = start('h6', ['iperf', '-s', '-p', '5001', '-i', '5', '-y', 'C'], 'iperf-server.csv')
    time.sleep(.5)
    report['tcp_start'] = time.time()
    client = start('h1', ['iperf', '-c', '10.0.0.6', '-p', '5001', '-t', '90', '-i', '5', '-y', 'C'], 'iperf-client.csv')
    attack = None
    counter_before = None
    snapshots = (out / 'paths.jsonl').open('w')
    logs.append(snapshots)
    print(args.case, ': recording 25 seconds of normal traffic.', flush=True)
    while client.poll() is None:
        now = time.time()
        if now - report['tcp_start'] > 115:
            raise RuntimeError('TCP test exceeded 115 seconds')
        current = tables()
        path = flow_path(current)
        snapshots.write(json.dumps({'time': now, 'path': path}) + '\n')
        snapshots.flush()
        if path and 'initial_path' not in report:
            report['initial_path'] = path
        if now - report['tcp_start'] >= 25 and attack is None:
            baseline.wait(timeout=5)
            assert baseline.returncode == 0 and 'Q2 BASELINE: IP=' + source_ip in controller_log()
            report['attack_path'] = flow_path(current, int(source[1:]), int(destination[1:]), 'icmp')
            assert report['attack_path'] == [int(source[1:]), int(destination[1:])], report['attack_path']
            report['path_before'] = path
            report['attack_start'] = time.time()
            attack = start(source, ['timeout', '--signal=INT', '10', 'hping3', '--icmp', '--flood', destination_ip], 'hping.log')
            print(args.case, ': flood started on the requested link.', flush=True)
        if attack is not None and 'Q2 BLOCKED: IP=' + source_ip in controller_log():
            if 'block_observed' not in report:
                report['block_observed'] = now
                print(args.case, ': source blocked; watching rerouting and recovery.', flush=True)
            elif counter_before is None:
                report['drop_rule_switches'] = [i for i, text in current.items()
                    if re.search(r'priority=5000,.*nw_src=' + re.escape(source_ip) + r' actions=drop', text)]
                (out / 'blocked-flows.json').write_text(json.dumps(current, indent=2) + '\n')
                counter_before = (now, source_counters(current[int(source[1:])]))
            elif 'counter_delta' not in report and now - counter_before[0] >= 1.5:
                after = source_counters(current[int(source[1:])])
                report['counter_delta'] = {key: after[key]-counter_before[1][key] for key in after}
                report['counter_window_s'] = now - counter_before[0]
                report['flood_running_during_counter_check'] = attack.poll() is None
        time.sleep(1)
    report['tcp_end'] = time.time()
    report['client_exit_code'] = client.returncode
    ping.wait(timeout=20)
    report['path_after'] = flow_path(tables())
    report['attacker_after'] = nodes[source].cmd('ping -c 3 -W 1 ' + destination_ip)
    report['drop_rules_after'] = sum('priority=5000,' in text and 'nw_src=' + source_ip in text for text in tables().values())
    report['blocked_sources'] = sorted(set(re.findall(r'Q2 BLOCKED: IP=(\S+)', controller_log())))
    # Keep the original samples alongside the flow-table observations.
    for p in set((ROOT / 'results/data').glob('qn[23]-*.jsonl')) - previous_files:
        (out / p.name).write_bytes(p.read_bytes())
finally:
    for process in reversed(processes):
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    net.stop()
    if controller is not None:
        controller.terminate()
        controller.wait(timeout=10)
    for log in logs:
        log.close()
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Saved:', out, flush=True)

subprocess.run([str(ROOT / '.venv/bin/python'), str(ROOT / 'tools/plot_qn4.py'), str(out)], check=True)
