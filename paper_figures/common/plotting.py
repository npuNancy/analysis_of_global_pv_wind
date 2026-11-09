"""Shared publication styling; importing this module does not render figures."""
from paper_figures.config import SSP_COLORS

def configure():
    import matplotlib as mpl
    mpl.rcParams.update({'font.family':'sans-serif','font.size':7,'axes.spines.top':False,
                         'axes.spines.right':False,'axes.linewidth':0.8,'legend.frameon':False})

def save_png(fig,path):
    from pathlib import Path
    path=Path(path)
    if path.suffix.lower()!='.png': raise ValueError('Project figures must be PNG')
    path.parent.mkdir(parents=True,exist_ok=True);fig.savefig(path,dpi=600,bbox_inches='tight',facecolor='white')

def export_panel_png(fig, path, bounds=None, close=True):
    """Export a full PNG or panel-group crop and verify text and image bounds."""
    from pathlib import Path
    import matplotlib.pyplot as plt
    from matplotlib.text import Text
    from matplotlib.patches import Rectangle
    from matplotlib.transforms import Bbox
    from PIL import Image
    from paper_figures.common.io import digest
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    region = Bbox.from_extents(*(bounds or [0, 0, 1, 1]))
    for artist in fig.findobj(Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        box = artist.get_window_extent(renderer).transformed(fig.transFigure.inverted())
        if box.x0 < -.002 or box.y0 < -.002 or box.x1 > 1.002 or box.y1 > 1.002:
            raise ValueError(f'Text outside canvas: {path.name}: {artist.get_text()}')
        if bounds and box.overlaps(region) and (
                box.x0 < region.x0 - .002 or box.y0 < region.y0 - .002 or
                box.x1 > region.x1 + .002 or box.y1 > region.y1 + .002):
            raise ValueError(f'Panel crop clips text: {path.name}: {artist.get_text()}')
    if bounds is None:
        fig.add_artist(Rectangle((0, 0), 1, 1, transform=fig.transFigure,
                                 fill=False, edgecolor='none', linewidth=0))
        save_png(fig, path)
    else:
        bbox = region.transformed(fig.transFigure).transformed(fig.dpi_scale_trans.inverted())
        fig.savefig(path, dpi=600, bbox_inches=bbox, facecolor='white', pad_inches=0)
    if close:
        plt.close(fig)
    with Image.open(path) as im:
        info = {'pixels': list(im.size), 'dpi': list(im.info.get('dpi', []))}
        im.verify()
    return {'path': path.name, 'image': info, 'sha256': digest(path),
            'figure_fraction_bounds': bounds, 'text_bounds_check': 'PASSED'}


def independent_y_ticks(ax, intervals=5):
    """Fit all displayed curves with padded, round ticks and a fixed interval count."""
    import numpy as np
    values=np.concatenate([np.asarray(line.get_ydata(),dtype=float) for line in ax.lines])
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite plotted values")
    minimum,maximum=float(values.min()),float(values.max())
    span=max(maximum-minimum,abs(maximum)*1e-6,1e-12)
    lower,upper=minimum-.06*span,maximum+.06*span
    exponent=int(np.floor(np.log10((upper-lower)/intervals)))
    for power in range(exponent,exponent+4):
        for factor in (1.,1.25,1.5,2.,2.5,3.,4.,5.,6.,8.):
            step=factor*10.**power
            first=int(np.ceil(upper/step-intervals-1e-10))
            last=int(np.floor(lower/step+1e-10))
            if first>last:
                continue
            anchor=int(np.clip(np.rint((lower+upper)/(2*step)-intervals/2),first,last))
            ticks=(anchor+np.arange(intervals+1,dtype=float))*step
            ticks[np.abs(ticks)<step*1e-10]=0.
            ax.set_yticks(ticks)
            ax.set_ylim(float(ticks[0]),float(ticks[-1]))
            if not (ticks[0]<minimum and maximum<ticks[-1]):
                raise ValueError("Clipped curve")
            np.testing.assert_allclose(np.diff(ticks),step,rtol=1e-10)
            return dict(lower=float(ticks[0]),upper=float(ticks[-1]),step=step,
                        intervals=intervals,ticks=ticks.tolist(),
                        data_minimum=minimum,data_maximum=maximum)
    raise ValueError("Unable to choose independent y ticks")
