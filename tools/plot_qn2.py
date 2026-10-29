"""Plot a saved Qn2 test. No controller or Mininet access is needed."""
import argparse
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
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

fig, ax = plt.subplots(figsize=SIZES['connectivity'])
values = np.full((3, 3), np.nan)
labels = np.full((3, 3), '', dtype=object)
checks = [(0, 0, 'h2_normal'), (0, 2, 'h2_after_block'),
          (1, 0, 'h1_normal'), (1, 1, 'h1_during_block'), (2, 2, 'h3_healthy')]
for row, column, key in checks:
    match = re.search(r'(\d+) packets transmitted, (\d+) received', report[key])
    if not match:
        parser.error('Cannot read ping summary: ' + key)
    sent, received = map(int, match.groups())
    values[row, column] = 100 * received / sent
    labels[row, column] = '%d/%d' % (received, sent)
colors = LinearSegmentedColormap.from_list('replies', [red, COLORS['neutral'], green])
ax.set_facecolor(COLORS['missing'])
sns.heatmap(values, mask=np.isnan(values), annot=labels, fmt='', cmap=colors,
            vmin=0, vmax=100, linewidths=3, linecolor='white',
            xticklabels=['Before flood', 'During block', 'After flood'],
            yticklabels=['h2 → h3', 'h1 → h6', 'h3 → h6'],
            cbar_kws={'label': 'Replies (%)', 'ticks': [0, 100], 'shrink': 0.7}, ax=ax)
for row, column in zip(*np.where(np.isnan(values))):
    ax.text(column + 0.5, row + 0.5, '—', ha='center', va='center', color=COLORS['gray'])
ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
ax.set(title='Connectivity by experiment stage', xlabel='Replies / sent; — = not measured')
ax.tick_params(axis='both', length=0)
save(fig, 'qn2-connectivity')
print('Saved PNG, SVG and PDF figures:', output)
