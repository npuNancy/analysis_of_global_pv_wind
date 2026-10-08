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
