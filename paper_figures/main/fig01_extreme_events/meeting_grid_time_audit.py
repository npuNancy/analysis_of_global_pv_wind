"""Audit published event definitions, actual temporal interpolation and coverage."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import netCDF4
import cftime
from paper_figures.config import ROOT
from paper_figures.common.io import write_json, digest
from utils.data_access.read_extreme_grid import find_records

BASE = ROOT / "paper_figures/main/fig01_extreme_events"
OUT = BASE / "outputs/meeting_grid"
SOURCE = OUT / "source_data"
UPSTREAM = Path('/work/home/acjpoxgsdu/project_climate/repos/extreme_event_definitions')
EXPECTED_SOURCE_SHA256 = '9a2e9524e5dc1f8dd6841a0420d8727abcedef6465c4fcebec014595621472a0'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reference(path, needle):
    lines = path.read_text().splitlines()
    index = next(i for i,line in enumerate(lines,1) if needle in line)
    return dict(path=str(path),line=index,source_line=lines[index-1],sha256=digest(path))


def source_audit():
    paths = [UPSTREAM/'registry.py', UPSTREAM/'tools/common.py']
    paths += sorted((UPSTREAM/'events').glob('*.py'))
    paths += [UPSTREAM/'grid_extreme_signals'/name for name in ('grid_io.py','grid_compute.py','unit_conversion.py')]
    checksum=hashlib.sha256()
    for path in paths:
        checksum.update(str(path.relative_to(UPSTREAM)).encode())
        checksum.update(path.read_bytes())
    require(checksum.hexdigest()==EXPECTED_SOURCE_SHA256, 'Upstream scientific source differs from published artifacts')
    io=UPSTREAM/'grid_extreme_signals/grid_io.py'
    compute=UPSTREAM/'grid_extreme_signals/grid_compute.py'
    units=UPSTREAM/'grid_extreme_signals/unit_conversion.py'
    cache=ROOT/'RQ1_extreme/global/grid/grid_common.py'
    refs=dict(
        source_hash_definition=reference(compute,'def implementation_identity'),
        reference_axis=reference(io,'self.reference ='),
        time_brackets=reference(io,'right = np.searchsorted'),
        interpolation_weights=reference(io,'np.divide(self.hours - source[left]'),
        actual_linear_interpolation=reference(io,'values = slab[r] * w'),
        cast_before_conversion=reference(io,'out[positions] = values.astype(np.float32)'),
        temperature_conversion=reference(units,'return (x - 273.15).astype(np.float32)'),
        event_specific_validity=reference(compute,'valid = {name: domain'),
        wind_icing=reference(UPSTREAM/'events/wind_icing.py','return (w["temp_C"]'),
        solar_icing=reference(UPSTREAM/'events/solar_icing.py','return (w["temp_C"]'),
        cache_all_event_intersection=reference(cache,'valid &= binary'),
        cache_actual_valid_count=reference(cache,'valid_counts[i] += vv.sum'),
        cache_valid_hours=reference(cache,'hh = valid_counts[i] * dt_hours'),
        cache_time_area=reference(cache,'time_area = float((ds["valid_hours"]'),
        cache_time_coverage=reference(cache,'table["time_coverage_pct"] ='),
    )
    return dict(upstream_root=str(UPSTREAM),scientific_source_sha256=checksum.hexdigest(),
                matches_published_source_sha256=True,files_hashed=len(paths),references=refs,
                interpolation='Each weather variable is linearly interpolated onto the technology reference timestamps before unit conversion and thresholding. This is not a timestamp relabel.',
                dtype='Raw slabs float32; interpolation weights float64; interpolated result cast to float32; Celsius conversion (float32 - 273.15).astype(float32).')


def global_coverage_audit():
    path=SOURCE/'annual_models.csv'
    frame=pd.read_csv(path)
    d=frame[frame.event.eq('icing') & frame.year.between(2050,2059)].copy()
    require(len(d)==4*3*2*10, 'Incomplete 2050s global icing coverage')
    require(not d.duplicated(['model','climate_ssp','tech','year']).any(),'Duplicate global annual coverage')
    require(d.coverage_pct.eq(100).all(),'Spatial coverage is not complete')
    require(d.time_coverage_pct.eq(100).all(),'All-event valid-time coverage is not complete')
    require(d.valid_area_km2.eq(d.reference_area_km2).all(),'Reference and valid areas differ')
    require(d.valid_area_km2.nunique()==1,'Global spatial support differs between products')
    keep=['model','climate_ssp','tech','year','coverage_pct','time_coverage_pct','valid_area_km2','reference_area_km2','exposure_days']
    d[keep].to_csv(SOURCE/'icing_global_coverage_audit.csv',index=False)
    levels=d.groupby(['model','climate_ssp','tech']).exposure_days.mean().unstack('tech')
    contrasts=levels.xs('ssp585',level='climate_ssp')-levels.xs('ssp126',level='climate_ssp')
    contrasts['solar_minus_wind_difference']=contrasts.solar-contrasts.wind
    contrasts.reset_index().to_csv(SOURCE/'icing_sampling_contrasts.csv',index=False)
    return dict(scope='All global published support, 2050-2059; four models, three SSPs, two products, ten years',
                source=str(path),source_sha256=digest(path),n_rows=len(d),area_km2=float(d.valid_area_km2.iloc[0]),
                coverage_pct_unique=d.coverage_pct.unique().tolist(),time_coverage_pct_unique=d.time_coverage_pct.unique().tolist(),
                formula='valid_hours[g,y] = dt_hours * sum_t(all_event_binary_valid[t,g]); time_area = sum_g(area[g] * valid_hours[g,y] / nominal_calendar_hours[y]); time_coverage_pct = 100 * sum_patch(time_area) / sum_patch(reference_area).',
                interpretation='This measures the actual all-event valid-time intersection, not merely timestamp completeness or the fraction of cells with any valid sample.',
                mask_effect_upper_bound_days_per_year=0.0,
                conclusion='The all-event valid mask removes no observed exposure time on this shared global support in 2050-2059, and cannot explain the wind/solar icing difference in this period.',
                pathway_contrasts_by_model=contrasts.reset_index().to_dict('records'),
                pathway_contrasts_mean=contrasts.mean().to_dict())


def native_year_audit():
    records=find_records(patch='R02C08',years=(2050,2059))
    require(len(records)==48,'Expected 48 indexed signal segments')
    rows=[]
    for record in records:
        with netCDF4.Dataset(record['path']) as ds:
            require(ds.source_sha256==EXPECTED_SOURCE_SHA256,'Published source hash differs')
            time=ds['time'];calendar=getattr(time,'calendar','standard')
            dates=netCDF4.num2date(time[:],time.units,calendar,only_use_cftime_datetimes=True)
            hours=np.asarray(netCDF4.date2num(dates,'hours since 1970-01-01',calendar),dtype=float)
            require(np.all(np.diff(hours)==3),'Non-three-hourly published time axis')
            years=np.array([date.year for date in dates])
            for year in sorted(set(years)&set(range(2050,2060))):
                selected=dates[years==year]
                first=cftime.datetime(int(year),1,1,calendar=calendar)
                end=cftime.datetime(int(year)+1,1,1,calendar=calendar)
                nominal=(end-first).total_seconds()/3600
                require(len(selected)*3==nominal,'Annual time axis is incomplete')
                rows.append(dict(model=record['model'],climate_ssp=record['climate_scenario'],tech=record['tech'],
                                 year=int(year),calendar=calendar,n_steps=len(selected),dt_hours=3,
                                 represented_hours=len(selected)*3,nominal_hours=nominal,
                                 first_time=str(selected[0]),last_time=str(selected[-1]),
                                 first_offset_hours=(selected[0]-first).total_seconds()/3600,
                                 last_offset_hours=(selected[-1]-first).total_seconds()/3600,
                                 signal_path=record['path']))
    frame=pd.DataFrame(rows)
    require(len(frame)==240,'Annual time audit matrix size')
    pairs=frame[frame.tech.eq('wind')].merge(frame[frame.tech.eq('solar')],on=['model','climate_ssp','year'],suffixes=('_wind','_solar'),validate='one_to_one')
    require(pairs.n_steps_wind.eq(pairs.n_steps_solar).all(),'Wind/solar annual step counts differ')
    require(pairs.nominal_hours_wind.eq(pairs.nominal_hours_solar).all(),'Wind/solar annual calendar duration differs')
    require((pairs.first_offset_hours_solar-pairs.first_offset_hours_wind).eq(1.5).all(),'Unexpected first-sample offset')
    require((pairs.last_offset_hours_solar-pairs.last_offset_hours_wind).eq(1.5).all(),'Unexpected last-sample offset')
    frame.to_csv(SOURCE/'icing_native_annual_time_axes.csv',index=False)
    return dict(scope='R02C08 time-coordinate metadata: 48 indexed 2050-2059 signal files, all four models and three SSPs',
                annual_rows=len(frame),paired_annual_rows=len(pairs),same_annual_n_steps=True,same_annual_calendar_hours=True,
                annual_step_counts=sorted(frame.n_steps.unique().tolist()),annual_hours=sorted(frame.nominal_hours.unique().tolist()),
                first_sample_offsets_hours=frame.groupby('tech').first_offset_hours.unique().map(list).to_dict(),
                last_sample_phase_difference_hours=1.5,
                interpretation='Wind and solar each contain every native-calendar three-hour slot. Annual step counts and duration are equal. Solar samples are genuinely 1.5 hours later; the final 22:30 sample interpolates the 21:00 value and the next-year 00:00 value. This is part of temporal sampling, not an unequal annual-duration or omitted-endpoint effect.')


def small_sample_audit():
    model,ssp,patch='BCC-CSM2-MR','ssp126','R02C08'
    n=240;ys=slice(130,133);xs=slice(127,130)
    records={tech:find_records(model=model,climate_scenario=ssp,patch=patch,tech=tech,years=(2050,2054))[0] for tech in ['wind','solar']}
    formal={};valid={};dates={}
    for tech,record in records.items():
        with netCDF4.Dataset(record['path']) as ds:
            require(ds.source_sha256==EXPECTED_SOURCE_SHA256,'Small-sample source hash')
            ds.set_auto_mask(False)
            formal[tech]=ds['signal_icing'][:n,ys,xs]
            arrays=[ds[key][:n,ys,xs] for key in ds.variables if key.startswith('signal_')]
            valid[tech]=np.logical_and.reduce([(a==0)|(a==1) for a in arrays])
            dates[tech]=netCDF4.num2date(ds['time'][:n],ds['time'].units,ds['time'].calendar)
            if tech=='wind':
                provenance=json.loads(ds.provenance);lat=ds['lat'][ys];lon=ds['lon'][xs]
    raw={};identities={};boundary={}
    for variable in ['tas','hurs']:
        path=Path(provenance['inputs'][variable]['path'])
        with netCDF4.Dataset(path) as ds:
            time=ds['time'];calendar=time.calendar
            start=netCDF4.date2num(dates['wind'][0],time.units,calendar)
            index=int(np.searchsorted(time[:],start))
            require(time[index]==start,'Raw meteorology does not share the wind reference sample')
            data=ds[variable][index:index+n+1,ys,xs]
            raw[variable]=np.ma.filled(data,np.nan).astype(np.float32)
            # Coordinates only: check raw support through the final solar interpolation bracket.
            endpoints=netCDF4.num2date(time[[0,-1]],time.units,calendar)
            needed=cftime.datetime(2060,1,1,calendar=calendar)
            require(endpoints[-1]>=needed,'Raw input cannot bracket the last solar sample of 2059')
            boundary[variable]=dict(first_source_time=str(endpoints[0]),last_source_time=str(endpoints[-1]),
                                    last_2059_solar_right_bracket=str(needed),right_bracket_available=True)
            unit=getattr(ds[variable],'units','K' if variable=='tas' else '%')
            require(unit in (['K','kelvin'] if variable=='tas' else ['%','percent']),'Unexpected raw units')
        identities[variable]=dict(path=str(path),bytes=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns)
    t0=(raw['tas'][:-1]-273.15).astype(np.float32)
    h0=np.clip(raw['hurs'][:-1],0,100).astype(np.float32)
    t1=(((raw['tas'][:-1].astype(float)+raw['tas'][1:].astype(float))/2).astype(np.float32)-273.15).astype(np.float32)
    h1=np.clip(((raw['hurs'][:-1].astype(float)+raw['hurs'][1:].astype(float))/2).astype(np.float32),0,100)
    calculated={'wind':(t0 < -2)&(h0>=85),'solar':(t1 < -2)&(h1>=85)}
    matches={tech:bool(np.array_equal(value,formal[tech]==1)) for tech,value in calculated.items()}
    require(all(matches.values()),'Raw weather does not reproduce formal icing flags')
    require(all(value.all() for value in valid.values()),'Small sample all-event mask contains missing time')
    differing=np.argwhere(calculated['wind']!=calculated['solar'])
    examples=[]
    for i,j,k in differing[:6]:
        examples.append(dict(wind_time=str(dates['wind'][i]),solar_time=str(dates['solar'][i]),lat=float(lat[j]),lon=float(lon[k]),
                             wind_temperature_c=float(t0[i,j,k]),wind_rh_pct=float(h0[i,j,k]),
                             solar_temperature_c=float(t1[i,j,k]),solar_rh_pct=float(h1[i,j,k]),
                             wind_signal=int(formal['wind'][i,j,k]),solar_signal=int(formal['solar'][i,j,k])))
    return dict(scope='BCC-CSM2-MR/ssp126/R02C08, first 240 time steps in 2050, 3x3 land cells',
                n_samples=int(t0.size),latitude=lat.tolist(),longitude=lon.tolist(),raw_inputs=identities,
                signals={tech:record['path'] for tech,record in records.items()},matches_published=matches,
                differing_wind_solar_samples=len(differing),icing_counts={tech:int(value.sum()) for tech,value in calculated.items()},
                all_event_valid_counts={tech:int(value.sum()) for tech,value in valid.items()},
                icing_removed_by_all_event_mask={tech:int(np.count_nonzero((formal[tech]==1)&~valid[tech])) for tech in formal},
                raw_input_year_boundary_support=boundary,examples=examples)


def main():
    SOURCE.mkdir(parents=True,exist_ok=True)
    path=BASE/'outputs/ssp_grid/event_definitions.json'
    records=json.loads(path.read_text())['records']
    rows=[];source_records=[]
    for record in records:
        p=Path(record['path'])
        with netCDF4.Dataset(p) as ds:
            t=ds['time'];dates=netCDF4.num2date(t[:8],t.units,calendar=t.calendar,only_use_cftime_datetimes=True)
            prov=json.loads(ds.provenance);definitions=json.loads(ds.event_definitions)
            require(ds.source_sha256==EXPECTED_SOURCE_SHA256,'2015 signal source hash differs')
            rows.append(dict(model=record['model'],climate_ssp=record['ssp'],tech=record['tech'],path=str(p),
                             first_time=str(dates[0]),next_time=str(dates[1]),phase_minutes=(dates[0].hour*60+dates[0].minute)%180,
                             calendar=t.calendar,n_times=len(t),reference_variable=ds.reference_variable,
                             grid_fingerprint=ds.grid_fingerprint,mask_fingerprint=ds.mask_fingerprint,time_fingerprint=ds.time_fingerprint,
                             icing_definition=definitions['icing'],low_resource_definition=definitions['low_resource'],
                             window_steps=ds.window_steps,mark_next_step=ds.mark_next_step,baseline_years=ds.baseline_years,
                             hurs_path=prov['inputs']['hurs']['path'],tas_path=prov['inputs']['tas']['path'],
                             low_resource_baseline_identity=prov['baseline_identity']))
            source_records.append(dict(model=record['model'],climate_ssp=record['ssp'],tech=record['tech'],signal_path=str(p),
                                       inputs=prov['inputs'],definitions=definitions,baseline_contract=prov['baseline_contract']))
    frame=pd.DataFrame(rows);frame.to_csv(SOURCE/'product_time_axes.csv',index=False)
    pairs=frame[frame.tech.eq('wind')].merge(frame[frame.tech.eq('solar')],on=['model','climate_ssp'],suffixes=('_wind','_solar'),validate='one_to_one')
    require(len(pairs)==12,'Twelve model/SSP pairs required')
    pairs['phase_offset_minutes']=(pairs.phase_minutes_solar-pairs.phase_minutes_wind)%180
    for key in ['icing_definition','hurs_path','tas_path','grid_fingerprint','mask_fingerprint']:
        pairs['same_'+key]=pairs[key+'_wind'].eq(pairs[key+'_solar'])
    require(pairs.same_icing_definition.all() and pairs.same_hurs_path.all() and pairs.same_tas_path.all(),'Different definitions or input weather')
    pairs.to_csv(SOURCE/'paired_time_axis_audit.csv',index=False)
    write_json(SOURCE/'raw_provenance.json',source_records)
    detailed=dict(status='PASSED',source=source_audit(),global_coverage=global_coverage_audit(),
                  annual_time_axes=native_year_audit(),small_sample=small_sample_audit(),script_sha256=digest(Path(__file__)))
    write_json(OUT/'icing_sampling_audit.json',detailed)
    write_json(OUT/'time_axis_audit.json',dict(status='PASSED',scope='2015 source metadata plus 2050s global coverage, native annual time axes and a small raw-weather reproduction',
               n_pairs=len(pairs),offsets_minutes=sorted(map(int,pairs.phase_offset_minutes.unique())),
               common_definition=sorted(frame.icing_definition.unique().tolist()),same_raw_temperature_and_humidity=True,
               comparison='Same thresholds and raw weather; solar linearly interpolates weather onto timestamps 90 minutes after the native wind grid before applying the threshold.',
               cache_mask='All-event valid-time intersection; global 2050-2059 weighted valid-time coverage is exactly 100% for both products, hence this mask contributes zero to the period discrepancy.',
               same_annual_wind_solar_steps_and_hours=True,detailed_audit=str(OUT/'icing_sampling_audit.json'),
               limitation='Raw-array reproduction is a 2160-sample diagnostic, not a global raw-array recomputation. Native time-coordinate audit covers all models/SSPs in representative patch R02C08. Coverage audit is global.',
               input_sha256=digest(path),code_sha256=digest(Path(__file__))))
    print(json.dumps(dict(status='PASSED',global_rows=detailed['global_coverage']['n_rows'],annual_rows=detailed['annual_time_axes']['annual_rows'],
                         small_sample=detailed['small_sample']['n_samples'],differing_samples=detailed['small_sample']['differing_wind_solar_samples'],
                         formal_matches=detailed['small_sample']['matches_published'],mask_effect_days=0.0,
                         source_sha256=detailed['source']['scientific_source_sha256']),indent=2))

if __name__=='__main__':main()
