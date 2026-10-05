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
