"""Plot a saved Qn2 test. No controller or Mininet access is needed."""
import argparse
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.ticker import FuncFormatter
from plot_style import apply_style, COLORS, DPI, FORMATS, SIZES

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('result', type=Path, help='result.json from tests/check_qn2.py')
parser.add_argument('--output', type=Path, help='directory for the figures')
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


# Separate the flood rate and detection levels so both have readable axes.
fig, (rate_ax, ema_ax) = plt.subplots(2, 1, sharex=True, figsize=SIZES['rate'])
times = [s['time'] - report['flood_start'] for s in samples]
block_time = report['block_observed'] - report['flood_start']
rate_ax.plot(times, [s['rate_pps'] / 1000 for s in samples], 'o', color=blue,
             markersize=4, label='5 s rate samples', clip_on=False)
rate_ax.set(ylabel='Rate (kpps)', title='h2: observed forwarding rate')
rate_ax.set_ylim(0, max(s['rate_pps'] for s in samples) / 1000 * 1.3)
peak = max(samples, key=lambda s: s['rate_pps'])
rate_ax.annotate('%.2f kpps' % (peak['rate_pps'] / 1000),
                 (peak['time'] - report['flood_start'], peak['rate_pps'] / 1000),
                 xytext=(8, 6), textcoords='offset points', fontsize=9)
ema_ax.plot(times, [s['baseline_before'] for s in samples], 'o-', color=green,
            markersize=3, label='Previous EMA')
ema_ax.plot(times, [s['threshold_pps'] for s in samples], 's--', color=red,
            markersize=3, label='Threshold (3 × EMA)')
thresholds = [s['threshold_pps'] for s in samples if s['threshold_pps'] is not None]
ema_ax.set(ylim=(0, max(thresholds) * 1.55), ylabel='Level (pps)',
           xlabel='Time from flood start (s)', title='EMA and threshold used for detection')
for ax in (rate_ax, ema_ax):
    ax.axvspan(0, report['flood_duration_seconds'], color=blue, alpha=0.06)
    ax.axvline(0, color=COLORS['gray'], linestyle=':', linewidth=1)
    ax.axvline(block_time, color=red, linestyle=':', linewidth=1,
               label='Block observed' if ax is rate_ax else None)
    ax.grid(axis='y', color=COLORS['grid'], linewidth=0.5)
    ax.legend(loc='upper right')
save(fig, 'qn2-rate')

fig, ax = plt.subplots(figsize=SIZES['enforcement'])
values = [report['s2_counter_delta']['drop'], report['s2_counter_delta']['forward']]
bars = ax.barh(['Dropped', 'Forwarded'], values, color=[red, blue], height=0.5)
ax.invert_yaxis()
ax.set_xlim(0, max(max(values), 1) * 1.25)
for bar, value in zip(bars, values):
    ax.annotate(format(value, ','), (value, bar.get_y() + bar.get_height()/2),
                xytext=(7, 0), textcoords='offset points', va='center')
ax.xaxis.set_major_formatter(FuncFormatter(lambda value, pos: '%g' % (value / 1000)))
ax.set(xlabel='Packet counter increase (thousands)',
       title='s2 after blocking h2 (%.2f s window)' % report['counter_window_seconds'])
save(fig, 'qn2-enforcement')

def ping_count(key):
    match = re.search(r'(\d+) packets transmitted, (\d+) received', report[key])
    sent, received = map(int, match.groups())
    return sent, received


# Compare the same host pair before and after the event, with counts shown.
fig, axes = plt.subplots(1, 2, sharey=True, figsize=SIZES['connectivity'])
comparisons = [
    ('Attacking source: h2 → h3', ['Before flood', 'After block'],
     ['h2_normal', 'h2_after_block'], [blue, red]),
    ('Legitimate traffic: h1 → h6', ['Before flood', 'During block'],
     ['h1_normal', 'h1_during_block'], [green, green]),
]
for ax, (title, stages, keys, colors) in zip(axes, comparisons):
    for i, (key, color) in enumerate(zip(keys, colors)):
        sent, received = ping_count(key)
        percent = 100 * received / sent
        ax.bar(i, percent, width=0.48, color=color)
        ax.text(i, percent + 4, '%d/%d replies' % (received, sent), ha='center', fontsize=9)
    ax.set(title=title, ylim=(0, 123), xticks=[0, 1], xticklabels=stages)
    ax.set_yticks([0, 50, 100])
    ax.grid(axis='y', color=COLORS['grid'], linewidth=0.5)
    ax.set_axisbelow(True)
axes[0].set_ylabel('Ping replies received (%)')
save(fig, 'qn2-connectivity')

# A short reading order for the README, using the same measured values.
fig, ax = plt.subplots(figsize=SIZES['overview'])
ax.axis('off')
detected = next(s for s in samples if s['status'] == 'detected')
sent, received = ping_count('h2_normal')
columns = [
    ('1. Normal traffic', 'h2 → h3 · before flood', '%d / %d' % (received, sent),
     'ping replies', 'EMA %.3f pps' % detected['baseline_before']),
    ('2. Anomaly detected', 'h2 · %.2f s after flood launch' % block_time,
     '%s pps' % format(detected['rate_pps'], ',.0f'), 'measured rate',
     'threshold %.3f pps' % detected['threshold_pps']),
    ('3. Source blocked', 's2 · sender still active',
     format(report['s2_counter_delta']['drop'], ','), 'packets dropped',
     '%d forwarded · %.2f s check' % (report['s2_counter_delta']['forward'],
                                     report['counter_window_seconds'])),
]
for x, (title, label, value, unit, detail) in zip([0.16, 0.50, 0.84], columns):
    ax.text(x, 0.91, title, ha='center', fontsize=11)
    ax.text(x, 0.77, label, ha='center', color=COLORS['gray'], fontsize=9)
    ax.text(x, 0.54, value, ha='center', fontsize=21)
    ax.text(x, 0.39, unit, ha='center', fontsize=10)
    ax.text(x, 0.22, detail, ha='center', fontsize=10)
for x in [0.33, 0.67]:
    ax.plot([x, x], [0.18, 0.94], color=COLORS['grid'], linewidth=0.7)
ax.plot([0.02, 0.98], [0.12, 0.12], color=COLORS['grid'], linewidth=0.7)
before_sent, before_received = ping_count('h1_normal')
during_sent, during_received = ping_count('h1_during_block')
ax.text(0.5, 0.01, 'Legitimate h1 → h6: %d/%d replies before flood; %d/%d during block' %
        (before_received, before_sent, during_received, during_sent),
        ha='center', fontsize=10, color=green)
ax.set(xlim=(0, 1), ylim=(-0.04, 1))
save(fig, 'qn2-overview')
print('Saved PNG, SVG and PDF figures:', output)
