"""Plot styling and grouped PNG export for the meeting follow-up figures."""
import numpy as np

from paper_figures.config import SSP_COLORS
from paper_figures.common.io import write_json
from paper_figures.common.plotting import export_panel_png

SSP_LABELS = {'ssp126': 'SSP1-2.6', 'ssp245': 'SSP2-4.5', 'ssp585': 'SSP5-8.5'}
SSP_MARKERS = {'ssp126': 'o', 'ssp245': 's', 'ssp585': '^'}
CLIMATE_COLOR, DEPLOY_COLOR, NET_COLOR = '#487A96', '#D39A54', '#333333'
MM = 1 / 25.4


def configure():
    import matplotlib as mpl
    mpl.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['Liberation Sans', 'DejaVu Sans'],
                         'font.size': 7, 'axes.titlesize': 7, 'axes.labelsize': 7, 'xtick.labelsize': 6,
                         'ytick.labelsize': 6, 'legend.fontsize': 6, 'axes.spines.top': False,
                         'axes.spines.right': False, 'axes.linewidth': 0.6, 'xtick.major.width': 0.6,
                         'ytick.major.width': 0.6, 'legend.frameon': False, 'lines.linewidth': 1.0})


def degree_axes(ax, xticks, yticks):
    """Degree-labelled, equally spaced graticule on a Plate Carree map axis."""
    import cartopy.crs as ccrs
    from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
    ax.set_xticks(list(xticks), crs=ccrs.PlateCarree()); ax.set_yticks(list(yticks), crs=ccrs.PlateCarree())
    ax.xaxis.set_major_formatter(LongitudeFormatter()); ax.yaxis.set_major_formatter(LatitudeFormatter())
    ax.tick_params(labelsize=5, length=2, width=0.4)
    ax.grid(True, lw=0.2, color='0.75')


_BORDERS = []


def draw_borders(ax, lw=0.25, color='0.35'):
    """Country outlines from the project Natural Earth copy (China and Taiwan merged)."""
    import cartopy.crs as ccrs
    from paper_figures.common.spatial import countries
    if not _BORDERS:
        _BORDERS.extend(g for _, _, g in countries())
    ax.add_geometries(_BORDERS, crs=ccrs.PlateCarree(), facecolor='none', edgecolor=color, lw=lw)


def panel_letter(ax, letter, x=-0.16, y=1.06):
    ax.text(x, y, letter, transform=ax.transAxes, fontsize=8, fontweight='bold', va='bottom', ha='left')


def model_band(ax, x, frame, ssp, label=True):
    """Plot the four-model mean and min-max range; frame has one column per model."""
    color = SSP_COLORS[ssp]
    ax.fill_between(x, frame.min(axis=1), frame.max(axis=1), color=color, alpha=0.18, linewidth=0)
    ax.plot(x, frame.mean(axis=1), color=color, label=SSP_LABELS[ssp] if label else None)


def support(values, reference=None):
    """Number of models whose value has the same non-zero sign as the ensemble mean."""
    values = np.asarray(values, dtype=float)
    ref = np.nanmean(values) if reference is None else reference
    return int(np.sum(np.sign(values) == np.sign(ref))) if ref != 0 else 0


def attach(ax, *extra_axes):
    """Register colour-bar or inset axes that must be exported with ``ax``."""
    ax._meeting_attached = list(getattr(ax, '_meeting_attached', [])) + list(extra_axes)


def group_bounds(fig, axes, pad=0.008):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    boxes = [ax.get_tightbbox(renderer).transformed(fig.transFigure.inverted()) for ax in axes]
    x0 = min(b.x0 for b in boxes) - pad; y0 = min(b.y0 for b in boxes) - pad
    x1 = max(b.x1 for b in boxes) + pad; y1 = max(b.y1 for b in boxes) + pad
    return [max(x0, 0), max(y0, 0), min(x1, 1), min(y1, 1)]


def hide_offscale_ticks(fig):
    """Tick labels outside the view interval are not drawn but still report text extents."""
    fig.canvas.draw()
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            lo, hi = sorted(axis.get_view_interval())
            eps = (hi - lo) * 1e-6
            for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                if not lo - eps <= tick.get_loc() <= hi + eps:
                    tick.label1.set_visible(False); tick.label2.set_visible(False)


def export(fig, folder, stem, groups, metadata=None):
    """Write the full PNG plus one PNG per panel group; groups maps suffix -> list of axes.

    Each group crop is rendered with the other panels and figure-level texts hidden, so the crop
    holds only the group's own axes, labels, legends and colour bars.
    """
    folder.mkdir(parents=True, exist_ok=True)
    hide_offscale_ticks(fig)
    records = []
    for suffix, axes in groups.items():
        keep = set(axes) | {cax for ax in axes for cax in getattr(ax, '_meeting_attached', [])}
        from matplotlib.text import Text
        hidden = [ax for ax in fig.axes if ax not in keep and ax.get_visible()]
        hidden += [t for ax in hidden for t in ax.findobj(Text) if t.get_visible()]
        texts = [t for t in fig.texts if t.get_visible()]
        legends = [l for l in fig.legends if l.get_visible()]
        legends += [t for l in legends for t in l.findobj(Text) if t.get_visible()]
        for artist in hidden + texts + legends:
            artist.set_visible(False)
        bounds = group_bounds(fig, list(keep))
        records.append(export_panel_png(fig, folder / f'{stem}_{suffix}.png', bounds, close=False))
        for artist in hidden + texts + legends:
            artist.set_visible(True)
    records.append(export_panel_png(fig, folder / f'{stem}.png'))
    write_json(folder / f'{stem}.json', dict(figure=stem, exports=records, **(metadata or {})))
    return records
