"""Compare three saved Qn2 runs. Each point or bar is one run."""
import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from plot_style import apply_style, COLORS, DPI, SIZES

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('data', nargs='?', type=Path,
                    default=ROOT / 'examples/qn2/repeats/summary.csv')
parser.add_argument('--output', type=Path, default=ROOT / 'figures/qn2-repeats')
args = parser.parse_args()
rows = list(csv.DictReader(args.data.open()))
args.output.mkdir(parents=True, exist_ok=True)
apply_style(plt)
fig, axes = plt.subplots(2, 2, figsize=SIZES['repeats'])
runs = ['Run ' + row['run'] for row in rows]
x = list(range(len(rows)))
blue, green, orange = COLORS['rate'], COLORS['ema'], COLORS['block']

ax = axes[0, 0]
delays = [float(row['observed_delay_s']) for row in rows]
ax.bar(x, delays, color=blue, width=0.5)
for i, value in enumerate(delays):
    ax.text(i, value + 0.04, '%.3f s' % value, ha='center', fontsize=9)
ax.set(title='(a) Observed block delay', ylabel='Seconds',
       ylim=(0, max(delays) * 1.3), xticks=x, xticklabels=runs)

ax = axes[0, 1]
rates = [float(row['rate_at_detection_pps']) / 1000 for row in rows]
ax.bar(x, rates, color=blue, width=0.5)
for i, value in enumerate(rates):
    ax.text(i, value + 0.3, '%.2f' % value, ha='center', fontsize=9)
ax.set(title='(b) ICMP rate at detection', ylabel='Thousand packets/s',
       ylim=(0, max(rates) * 1.3), xticks=x, xticklabels=runs)

ax = axes[1, 0]
drops = [int(row['drop_counter_increase']) for row in rows]
ax.bar(x, [value / 1000 for value in drops], color=orange, width=0.5)
for i, value in enumerate(drops):
    ax.text(i, value / 1000 + 3, format(value, ','), ha='center', fontsize=9)
    ax.text(i, 7, '%s forwarded' % rows[i]['forward_counter_increase'],
            ha='center', color='white', fontsize=8)
ax.set(title='(c) After blocking: about 1.5 s per run', ylabel='Thousand packets dropped',
       ylim=(0, max(drops) / 1000 * 1.3), xticks=x, xticklabels=runs)

ax = axes[1, 1]
for i, row in enumerate(rows):
    for key, color, marker, offset, label in [
            ('h2_after_block_replies', orange, 'o', 9, 'h2 after block'),
            ('h1_during_block_replies', green, 's', -9, 'h1 during block')]:
        received, sent = map(int, row[key].split('/'))
        percent = 100 * received / sent
        ax.plot(percent, i, marker, color=color, markersize=6,
                label=label if i == 0 else None)
        ax.annotate(row[key], (percent, i), xytext=(offset, 0),
                    textcoords='offset points', va='center',
                    ha='left' if offset > 0 else 'right', fontsize=9)
ax.set(title='(d) Blocked h2; reachable h1', xlabel='Ping replies received (%)',
       yticks=x, yticklabels=runs, xticks=[0, 50, 100], xlim=(-12, 112),
       ylim=(-0.6, len(rows) - 0.4))
ax.invert_yaxis()
ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.01), ncol=2, fontsize=8)
ax.set_title('(d) Blocked h2; reachable h1', pad=32)
for ax in axes.flat:
    ax.grid(axis='y', color=COLORS['grid'], linewidth=0.5)
    ax.set_axisbelow(True)
sns.despine(fig=fig)
fig.tight_layout(h_pad=2.4, w_pad=2)
fig.savefig(args.output / 'qn2-repeats.png', dpi=DPI,
            facecolor='white', bbox_inches='tight')
plt.close(fig)
print('Saved:', args.output / 'qn2-repeats.png')
