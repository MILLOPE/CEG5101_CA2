"""Plot a saved Qn2 test. No controller or Mininet access is needed."""
import argparse
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from plot_style import apply_style, COLORS, DPI, FORMATS, SIZES

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('result', type=Path, help='result.json from tests/check_qn2.py')
parser.add_argument('--output', type=Path, help='directory for PNG and SVG figures')
args = parser.parse_args()
report = json.loads(args.result.read_text())
output = args.output or args.result.parent / 'figures'
output.mkdir(parents=True, exist_ok=True)
samples = [json.loads(line) for line in
           (args.result.parent / report['samples_file']).read_text().splitlines() if line.strip()]
samples = sorted((s for s in samples if s['source'] == '10.0.0.2'), key=lambda s: s['time'])
if not samples:
    parser.error('No h2 samples were recorded.')

apply_style(plt)
blue, green, red = COLORS['rate'], COLORS['ema'], COLORS['block']


def save(fig, name):
    sns.despine(fig=fig)
    fig.tight_layout()
    for ext in FORMATS:
        fig.savefig(output / (name + '.' + ext), dpi=DPI, facecolor='white', bbox_inches='tight')
    plt.close(fig)


# The threshold uses the previous EMA, before this sample updates it.
fig, ax = plt.subplots(figsize=SIZES['rate'])
times = [s['time'] - report['flood_start'] for s in samples]
ax.plot(times, [s['rate_pps'] for s in samples], 'o-', color=blue,
        linewidth=1.5, markersize=4, label='Observed rate')
ax.plot(times, [s['baseline_before'] for s in samples], '.-', color=green,
        label='Previous EMA')
ax.plot(times, [s['threshold_pps'] for s in samples], '--', color=red,
        label='Threshold (3 × previous EMA)')
ax.axvspan(0, report['flood_duration_seconds'], color=blue, alpha=0.06)
ax.axvline(0, color=COLORS['gray'], linestyle=':', linewidth=1)
ax.axvline(report['block_observed'] - report['flood_start'], color=red,
           linestyle=':', linewidth=1, label='Block observed')
ax.set_yscale('symlog', linthresh=2)
ax.set_ylim(0, max(s['rate_pps'] for s in samples) * 2)
ax.set(xlabel='Time from flood start (s)', ylabel='ICMP requests (pps, symlog)',
       title='h2: observed rate and anomaly threshold')
ax.grid(axis='y', color='#e5e5e5', linewidth=0.5)
ax.legend(loc='lower left', bbox_to_anchor=(0, 1.18), ncol=2, borderaxespad=0)
save(fig, 'qn2-rate')

fig, ax = plt.subplots(figsize=SIZES['enforcement'])
values = [report['s2_counter_delta']['drop'], report['s2_counter_delta']['forward']]
bars = ax.barh(['Dropped', 'Forwarded'], values, color=[red, blue], height=0.5)
ax.invert_yaxis()
ax.set_xlim(0, max(max(values), 1) * 1.25)
for bar, value in zip(bars, values):
    ax.annotate(format(value, ','), (value, bar.get_y() + bar.get_height()/2),
                xytext=(7, 0), textcoords='offset points', va='center')
ax.set(xlabel='Increase in matching packet counters',
       title='s2 after blocking h2 (%.2f s window)' % report['counter_window_seconds'])
save(fig, 'qn2-enforcement')

fig, ax = plt.subplots(figsize=SIZES['connectivity'])
checks = [('h2 → h3\nBefore flood', 'h2_normal'),
          ('h2 → h3\nAfter block', 'h2_after_block'),
          ('h1 → h6\nDuring block', 'h1_during_block'),
          ('h3 → h6\nAfter flood', 'h3_healthy')]
for i, (label, key) in enumerate(checks):
    match = re.search(r'(\d+) packets transmitted, (\d+) received', report[key])
    if not match:
        parser.error('Cannot read ping summary: ' + key)
    sent, received = map(int, match.groups())
    ax.bar(i, 100 * received / sent, width=0.5, color=red if i == 1 else green)
    ax.text(i, 100 * received / sent + 4, '%d/%d' % (received, sent), ha='center')
ax.set_xticks(range(len(checks)), [label for label, _ in checks])
ax.set(ylim=(0, 119), ylabel='Ping replies received (%)', title='Connectivity checks')
ax.set_yticks([0, 25, 50, 75, 100])
ax.grid(axis='y', color='#e5e5e5', linewidth=0.5)
ax.set_axisbelow(True)
save(fig, 'qn2-connectivity')
print('Saved PNG, SVG and PDF figures:', output)
