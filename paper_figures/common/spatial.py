"""Country assignment with explicit unassigned and boundary-ambiguous classes."""
import numpy as np
import shapefile
from shapely.geometry import shape
from shapely.ops import unary_union
import shapely
from paper_figures.config import SHAPEFILE

def countries(path=SHAPEFILE):
    grouped={}; names={}
    with shapefile.Reader(str(path),encoding='utf-8') as reader:
        for rec in reader.iterShapeRecords():
            a=rec.record.as_dict();iso=a['ADM0_A3'];name=a['NAME']
            if iso in ('CHN','TWN'):iso='CHN';name='China'
            if not iso or iso=='-99':raise ValueError(f'Invalid country identifier: {a}')
            g=shape(rec.shape.__geo_interface__)
            if not g.is_valid:g=shapely.make_valid(g)
            grouped.setdefault(iso,[]).append(g);names[iso]=name
    return [(iso,names[iso],unary_union(grouped[iso])) for iso in sorted(grouped)]

def assign(lon,lat,geometries):
    x=(np.asarray(lon)+180)%360-180;y=np.asarray(lat)
    ids=np.full(len(x),'UNASSIGNED',dtype=object);hits=np.zeros(len(x),dtype=int)
    for iso,name,g in geometries:
        w,s,e,n=g.bounds;sel=np.flatnonzero((x>=w)&(x<=e)&(y>=s)&(y<=n))
        matched=sel[shapely.intersects_xy(g,x[sel],y[sel])]
        ids[matched]=iso;hits[matched]+=1
    ids[hits>1]='AMBIGUOUS'
    return ids
