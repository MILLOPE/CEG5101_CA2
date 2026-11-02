"""Read a Qn4 run and plot link cost, ping loss and receiver throughput."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess


def summarize(folder):
    report = json.loads((folder / 'result.json').read_text())
    start = report['attack_start']
    samples = [json.loads(line) for p in folder.glob('qn3-*.jsonl') for line in p.read_text().splitlines()]
    paths = [json.loads(line) for line in (folder / 'paths.jsonl').read_text().splitlines()]
    source, destination = [int(name[1:]) for name in report['case'].split('-')]
    edge = tuple(sorted((source, destination)))
    link = [row for row in samples if (row['src'], row['dst']) == edge]
    affected = [row for row in link if row['anomaly']]
    penalty_end = next(row['time'] for row in link if affected and row['time'] > affected[-1]['time'] and not row['anomaly'])
    report['penalty_end'] = penalty_end
    q2 = [json.loads(line) for p in folder.glob('qn2-*.jsonl') for line in p.read_text().splitlines()]
    detected = next(row['time'] for row in q2 if row['status'] == 'detected' and row['source'] == '10.0.0.%d' % source)
    report['detection_seconds'] = detected - start
    report['block_observed_seconds'] = report['block_observed'] - start
    report['anomaly_links'] = sorted({(row['src'], row['dst']) for row in samples if row['anomaly']})

    decoded = subprocess.check_output(['tcpdump', '-tt', '-n', '-r', str(folder / 'h1-icmp.pcap')],
                                      text=True, stderr=subprocess.DEVNULL)
    sent, received = {}, set()
    for line in decoded.splitlines():
        match = re.search(r'^([\d.]+).*ICMP echo (request|reply).*seq (\d+)', line)
        if match:
            stamp, kind, seq = float(match[1]), match[2], int(match[3])
            if kind == 'request':
                sent[seq] = stamp
            else:
                received.add(seq)
    ping = re.search(r'(\d+) packets transmitted, (\d+) received', (folder / 'h1-ping.log').read_text())
    report['ping'] = {'sent': len(sent), 'received': len(set(sent) & received),
                      'loss_pct': 100 * len(set(sent) - received) / len(sent)}
    assert (len(sent), len(set(sent) & received)) == (int(ping[1]), int(ping[2]))
    assert '0 packets dropped by kernel' in (folder / 'tcpdump.log').read_text()

    metrics = []
    for row in csv.reader((folder / 'iperf-server.csv').open()):
        if len(row) != 9 or '-' not in row[6]:
            continue
        begin, end = [float(value) for value in row[6].split('-')]
        if not 0 < end-begin <= 5.1:
            continue  # Skip iperf's final whole-connection summary.
        end_time = datetime.strptime(row[0], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).timestamp()
        begin_time = end_time - (end-begin)
        seqs = {seq for seq, stamp in sent.items() if begin_time <= stamp < end_time}
        replies = len(seqs & received)
        metrics.append({'start_time': begin_time, 'end_time': end_time,
                        'time_s': (begin_time+end_time)/2-start,
                        'receiver_mbps': float(row[8])/1e6,
                        'ping_sent': len(seqs), 'ping_received': replies,
                        'loss_pct': 100*(len(seqs)-replies)/len(seqs) if seqs else None})
    with (folder / 'metrics.csv').open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(metrics[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(metrics)
    report['zero_throughput_intervals'] = [[row['start_time']-start, row['end_time']-start]
                                            for row in metrics if row['receiver_mbps'] == 0]
    report['minimum_receiver_mbps'] = min(row['receiver_mbps'] for row in metrics)

    phases = {'before': (report['tcp_start'], start), 'during': (start, penalty_end),
              'after': (penalty_end, report['tcp_end'])}
    report['phases'] = {}
    for name, (begin, end) in phases.items():
        seqs = {seq for seq, stamp in sent.items() if begin <= stamp < end}
        bins = [row for row in metrics if row['start_time'] >= begin and row['end_time'] <= end]
        observed = [tuple(row['path']) for row in paths if begin <= row['time'] < end and row['path']]
        report['phases'][name] = {'ping_sent': len(seqs), 'ping_received': len(seqs & received),
                                  'loss_pct': 100*len(seqs-received)/len(seqs) if seqs else None,
                                  'receiver_mbps': sum(row['receiver_mbps'] for row in bins)/len(bins) if bins else None,
                                  'paths': [list(path) for path in Counter(observed)]}
    report['rerouted'] = any(path != report['path_before'] for path in report['phases']['during']['paths'])
    base = {(row['src'], row['dst']): row['base_cost'] for row in samples}
    report['initial_base_path_cost'] = sum(base[tuple(sorted((u,v)))] for u,v in zip(report['initial_path'],report['initial_path'][1:]))
    # Current costs can differ from the costs at which an existing flow was installed.
    report['route_cost_samples'] = []
    comparison = None
    for observation in paths:
        latest = {(row['src'], row['dst']): row['dynamic_cost'] for row in samples if row['time'] <= observation['time']}
        edges = [tuple(sorted((u,v))) for u,v in zip(observation['path'],observation['path'][1:])]
        if edges and all(edge in latest for edge in edges):
            report['route_cost_samples'].append({'time': observation['time'], 'path': observation['path'],
                                                  'cost': sum(latest[edge] for edge in edges)})
            if comparison is None and observation['time'] >= start and observation['path'] != report['path_before']:
                sampled = max(row['time'] for row in samples if row['time'] <= observation['time'])
                old_edges = [tuple(sorted((u,v))) for u,v in zip(report['path_before'],report['path_before'][1:])]
                comparison = {'case': report['case'], 'observed_s': observation['time']-start,
                              'sample_age_s': observation['time']-sampled,
                              'old_path': report['path_before'], 'old_cost': sum(latest[edge] for edge in old_edges),
                              'new_path': observation['path'], 'new_cost': sum(latest[edge] for edge in edges)}
    report['route_comparison'] = comparison
    if comparison is not None:
        with (folder / 'route_costs.csv').open('w', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=list(comparison), lineterminator='\n')
            writer.writeheader()
            writer.writerow({key: '-'.join('s%d'%i for i in value) if key.endswith('_path') else value
                             for key, value in comparison.items()})
    recovered = any(path == report['path_before'] for path in report['phases']['after']['paths'])
    report['checks'] = {
        'all_hosts_reachable': report['pingall_loss_percent'] == 0,
        'requested_attack_link': report['attack_path'] == [source, destination],
        'source_blocked': len(report['drop_rule_switches']) == report['drop_rules_after'] == 6
                          and report['blocked_sources'] == ['10.0.0.%d' % source]
                          and '100% packet loss' in report['attacker_after'],
        'forwarding_stopped': report['counter_delta']['drop'] > 0 and report['counter_delta']['forward'] == 0
                              and report['flood_running_during_counter_check'],
        'correct_anomaly_links': report['anomaly_links'] == [edge],
        'cost_penalty_and_recovery': bool(affected) and all(row['anomaly_penalty'] == 20 for row in affected),
        'legitimate_connected': all(phase['ping_received'] > 0 and phase['receiver_mbps'] is not None
                                    and phase['receiver_mbps'] > 0 for phase in report['phases'].values()),
        'route_recovered': recovered,
        'tcp_finished': report['client_exit_code'] == 0}
    if edge in [tuple(sorted(pair)) for pair in zip(report['path_before'],report['path_before'][1:])]:
        report['checks']['affected_route_changed'] = report['rerouted']
    if report['rerouted']:
        report['checks']['lower_cost_in_latest_sample'] = comparison is not None and comparison['new_cost'] < comparison['old_cost']
    report['passed'] = all(report['checks'].values())
    (folder / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    return report, link, metrics


def plot(folder, report, link, metrics):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from plot_style import apply_style, COLORS
    apply_style(plt)
    start = report['attack_start']
    end = report['penalty_end']-start
    fig, axes = plt.subplots(3, 1, figsize=(8.2, 7.2), sharex=True)
    fig.subplots_adjust(left=.12, right=.97, top=.86, bottom=.1, hspace=.22)
    source, destination = report['case'].split('-')
    fig.suptitle('%s → %s ICMP flood · h1 → h6 TCP' % (source,destination), x=.12, y=.97, ha='left', fontsize=15)
    before = '–'.join('s%d'%i for i in report['path_before'])
    alternatives = [path for path in report['phases']['during']['paths'] if path != report['path_before']]
    during = ' / '.join('–'.join('s%d'%i for i in path) for path in alternatives) or before
    after = ' / '.join('–'.join('s%d'%i for i in path) for path in report['phases']['after']['paths'])
    fig.text(.12, .91, 'TCP: %s  →  %s  →  %s' % (before,during,after), fontsize=10)
    fig.text(.12, .875, 'Cost: s%s–s%s   |   Flood: shaded   |   Detected: dotted   |   Penalty ends: dashed'
             % (source[1:],destination[1:]), fontsize=8)
    fig.text(.12, .025, 'ICMP probes: 1/s; loss and throughput: 5 s bins. TCP and ICMP may use different paths.', fontsize=8)
    for ax in axes:
        ax.axvspan(0, report['flood_seconds'], color=COLORS['block'], alpha=.1)
        ax.axvline(report['detection_seconds'], color=COLORS['block'], linestyle=':', linewidth=1)
        ax.axvline(end, color=COLORS['gray'], linestyle='--', linewidth=1)
        ax.grid(axis='y', color=COLORS['grid'], linewidth=.6)
    axes[0].plot([row['time']-start for row in link], [row['normalized_cost'] for row in link],
                 '-o', color=COLORS['rate'], markersize=3)
    axes[0].axhline(1, color=COLORS['gray'], linestyle=':', linewidth=.8)
    axes[0].set_ylabel('Link cost / base cost')
    axes[0].set_ylim(bottom=0)
    points = [row for row in metrics if row['loss_pct'] is not None]
    axes[1].bar([row['time_s'] for row in points], [row['loss_pct'] for row in points],
                width=4.1, color=COLORS['block'])
    axes[1].set_ylabel('ICMP loss (%)')
    axes[1].set_ylim(0, max(25, max(row['loss_pct'] for row in points)*1.2))
    if all(row['loss_pct'] == 0 for row in points):
        axes[1].text(.02, .7, '0% observed loss', transform=axes[1].transAxes, fontsize=9)
    axes[2].plot([row['time_s'] for row in metrics], [row['receiver_mbps'] for row in metrics],
                 '-o', color=COLORS['ema'], markersize=3)
    axes[2].set_ylabel('TCP rate at h6 (Mbps)')
    axes[2].set_ylim(bottom=0)
    lowest = min(metrics, key=lambda row: row['receiver_mbps'])
    if lowest['receiver_mbps'] < .01:
        axes[2].annotate('%.4f Mbps' % lowest['receiver_mbps'],
                         xy=(lowest['time_s'], lowest['receiver_mbps']),
                         xytext=(lowest['time_s']+8, 8), fontsize=9,
                         arrowprops={'arrowstyle': '->', 'color': COLORS['gray'], 'lw': .8})
    axes[2].set_xlabel('Time from flood start (s)')
    for ax in axes:
        ax.set_xlim(-26, report['tcp_end']-start+4)
    fig.savefig(folder/'qn4.png', dpi=300, facecolor='white')
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    report, link, metrics = summarize(args.folder)
    plot(args.folder, report, link, metrics)
    print('PASS' if report['passed'] else 'FAIL', report['case'], report['checks'])
    raise SystemExit(0 if report['passed'] else 1)
