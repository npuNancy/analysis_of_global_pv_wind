"""Annual metrics using the original generation_loss baseline and metric kernels."""
import sys
from pathlib import Path
import cftime
import numpy as np
import xarray as xr


def annual_metrics(cf,events,dates,years,windows,step_hours,reference_root):
    """Inputs use 1 MW reference capacity; preserve event missingness and signs."""
    source=str(Path(reference_root)/'loss')
    if source not in sys.path:sys.path.insert(0,source)
    from generation_loss.baseline import compute_cf_normal_for_range,align_cf_normal_to_time
    from generation_loss.metrics import calculate_signal_metrics
    yy=np.array([d.year for d in dates]);calendar=getattr(dates[0],'calendar','proleptic_gregorian')
    n=cf.shape[1]
    fields=['generation_per_mw','cf_mean','net_loss_per_mw','positive_loss_per_mw','normal_annual_per_mw',
            'event_normal_per_mw','event_actual_per_mw','event_hours','loss_event_hours','loss_hours',
            'cf_valid_count','signal_valid_count','loss_valid_count']
    out={name:np.full((len(years),n),np.nan) for name in fields}
    expected=np.array([(cftime.datetime(int(y)+1,1,1,calendar=calendar)-
                       cftime.datetime(int(y),1,1,calendar=calendar)).total_seconds()/3600 for y in years])
    cfds=xr.Dataset({'cf':(('time','station'),cf)},coords={'time':dates,'station':np.arange(n),
        'station_id':('station',np.arange(n).astype(str)),'capacity_mw':('station',np.ones(n))})
    sig=xr.Dataset({'signal_all':(('time','station'),np.where(events<0,np.nan,events))},coords={'time':dates,'station':np.arange(n)})
    baselines=[]
    for first,last in windows:
        normal=compute_cf_normal_for_range(cfds,sig,['signal_all'],first,last,snapshot_year=(first+last)//2)
        baselines.append(dict(years=[first,last],month_hour_idx=normal.month_hour_idx.values.copy(),
                              cf_normal=normal.cf_normal.values.copy(),count=normal.baseline_count.values.copy()))
        for i,year in enumerate(years):
            if not first<=year<=last:continue
            selected=np.flatnonzero(yy==year)
            if len(selected)*step_hours!=expected[i]:raise ValueError(f'Incomplete native time axis {year}')
            data=cfds.isel(time=selected).copy();s=sig.signal_all.isel(time=selected)
            data['cf_normal']=align_cf_normal_to_time(data,normal)
            data['time_step_hours']=xr.DataArray(np.full(len(selected),step_hours),dims='time',coords={'time':data.time})
            result=calculate_signal_metrics(data,s,'all',metrics=('absolute_loss','net_loss','event_duration'))
            for destination,source_name in [('net_loss_per_mw','net_generation_loss_mwh_all'),
                ('positive_loss_per_mw','generation_loss_mwh_all'),('normal_annual_per_mw','normal_all_generation_mwh_all'),
                ('event_normal_per_mw','normal_generation_mwh_all'),('event_actual_per_mw','actual_generation_mwh_all'),
                ('loss_event_hours','event_duration_hours_all'),('loss_hours','loss_hours_all')]:
                out[destination][i]=result[source_name].values
            values=cf[selected];valid=np.isfinite(values)
            counts=valid.sum(axis=0);out['cf_valid_count'][i]=counts
            generation=np.where(valid,values,0).sum(axis=0,dtype='f8')*step_hours
            generation[counts!=len(selected)]=np.nan
            out['generation_per_mw'][i]=generation;out['cf_mean'][i]=generation/expected[i]
            out['signal_valid_count'][i]=(events[selected]>=0).sum(axis=0)
            out['event_hours'][i]=(events[selected]==1).sum(axis=0)*step_hours
            out['loss_valid_count'][i]=(valid & np.isfinite(data.cf_normal.values) & (events[selected]>=0)).sum(axis=0)
    out['expected_hours']=expected
    return out,baselines
