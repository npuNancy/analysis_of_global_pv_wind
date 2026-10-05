"""Shared analysis definitions for the published BCSD-v2 products."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'paper_figures/prepare/outputs'
MODELS = ('CANESM5', 'MPI-ESM1-2-HR', 'MRI-ESM2-0', 'BCC-CSM2-MR')
SSPS = ('ssp126', 'ssp245', 'ssp585')
TECHS = ('wind', 'solar')
SNAPSHOTS = (2030, 2040, 2050)
EVENTS = {'wind': ('high_temp', 'high_wind', 'hot_humid', 'icing', 'low_resource'),
          'solar': ('cold_highwind', 'freezing_rain', 'high_humidity', 'icing', 'low_resource', 'rainstorm')}
STATION_FILES = dict(zip(SSPS, ('stations_SSP1-2.6.csv','stations_SSP2-4.5.csv','stations_SSP5-6.0.csv')))
SHAPEFILE = ROOT / 'data/maps/natural_earth/ne_110m_admin_0_countries.shp'
MIN_TIME_COVERAGE = 0.99
INDEXES = {
 'cf_grid': Path('/work/home/acjpoxgsdu/cf_grid/cf_grid_v2/runtime/authoritative_index.json'),
 'cf_stations': Path('/work/home/acjpoxgsdu/cf_stations/cf_stations_v2/index/authoritative_index.json'),
 'extreme_grid': Path('/work/home/acjpoxgsdu/extreme_grid/extreme_grid_v2/runtime/authoritative_index.json'),
 'extreme_stations': Path('/work/home/acjpoxgsdu/extreme_stations_new/extreme_stations_v2/runtime/authoritative_index.json'),
 'loss_stations': Path('/work/home/acjpoxgsdu/generation_loss_stations/loss_stations_v2/runtime/completion.json'),
}
LOSS_VARIABLES = {'net_mwh':'net_generation_loss_mwh', 'positive_mwh':'generation_loss_mwh',
                  'normal_event_mwh':'normal_generation_mwh', 'normal_annual_mwh':'normal_all_generation_mwh',
                  'actual_event_mwh':'actual_generation_mwh', 'event_hours':'event_duration_hours'}
SSP_COLORS = dict(zip(SSPS, ('#1d3b6f','#b77c19','#9e1b1b')))
