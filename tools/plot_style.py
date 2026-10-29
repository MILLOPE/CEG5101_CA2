"""Shared settings for the report figures. Sizes are in inches."""
DPI = 300
FONT = 'DejaVu Serif'
FONT_SIZE = 10
LINE_WIDTH = 1.5
COLORS = {'rate': '#0072B2', 'ema': '#009E73', 'block': '#D55E00', 'gray': '#777777'}
SIZES = {'rate': (7.0, 3.3), 'enforcement': (6.4, 2.5), 'connectivity': (7.0, 3.1)}
FORMATS = ('png', 'svg', 'pdf')


def apply_style(plt):
    import seaborn as sns
    sns.set_theme(context='paper', style='ticks', font=FONT,
                  palette=list(COLORS.values()))
    plt.rcParams.update({
        'font.family': FONT, 'font.size': FONT_SIZE, 'mathtext.fontset': 'stix',
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.linewidth': 0.7, 'lines.linewidth': LINE_WIDTH,
        'xtick.direction': 'out', 'ytick.direction': 'out',
        'legend.frameon': False, 'legend.fontsize': FONT_SIZE - 1,
        'pdf.fonttype': 42, 'ps.fonttype': 42, 'svg.fonttype': 'none',
    })
