"""Checks for country map aggregation, missingness and capacity encodings."""
import unittest
import numpy as np
import pandas as pd
from shapely.geometry import box

from prepare_country_exposure import map_table, assign_countries
from plot_country_exposure_maps import circle_area


class CountryMapTests(unittest.TestCase):
    def fixtures(self):
        grids, stations = [], []
        for m in range(1, 5):
            for tech, base, future, cap, days in (("wind",10,20,1,10),("solar",20,40,3,30)):
                common = dict(country="Example", country_iso3="EXA", model=str(m), scenario="ssp126", tech=tech)
                for start, value in ((2030,base),(2050,future)):
                    for year in range(start,start+10):
                        grids.append({**common,"year":year,"grid_days":value*m,"grid_coverage_pct":100})
                for year in range(2050,2060):
                    stations.append({**common,"year":year,"capacity_gw":cap,"valid_capacity_gw":cap,
                        "capacity_days_gw":cap*days*m,"station_days":days*m,"capacity_coverage_pct":100,
                        "station_count":1,"valid_station_count":1})
        return pd.DataFrame(grids), pd.DataFrame(stations)

    def test_decades_models_and_capacity_weighting(self):
        grid, station = self.fixtures()
        result = map_table(grid,station,list("1234"))
        combined = result[(result.model=="ensemble_mean") & (result.tech=="combined")].iloc[0]
        self.assertAlmostEqual(combined.grid_2030_days,75)
        self.assertAlmostEqual(combined.grid_2050_days,150)
        self.assertAlmostEqual(combined.grid_change_days,75)
        self.assertAlmostEqual(combined.station_2050_days,62.5)
        self.assertAlmostEqual(combined.capacity_gw,4)

    def test_missing_year_is_not_zero_or_short_decade(self):
        grid, station = self.fixtures()
        grid = grid[~((grid.model=="4") & (grid.tech=="wind") & (grid.year==2051))]
        result = map_table(grid,station,list("1234"))
        row = result[(result.model=="ensemble_mean") & (result.tech=="wind")].iloc[0]
        self.assertTrue(np.isnan(row.grid_2050_days))
        self.assertTrue(np.isnan(row.grid_change_days))
        self.assertAlmostEqual(row.station_2050_days,25)

    def test_missing_exposure_reduces_valid_capacity_only(self):
        grid, station = self.fixtures()
        solar = station.tech=="solar"
        station.loc[solar,["valid_capacity_gw","capacity_days_gw","valid_station_count"]]=0
        station.loc[solar,"station_days"]=np.nan
        station.loc[solar,"capacity_coverage_pct"]=0
        result=map_table(grid,station,list("1234"))
        row=result[(result.model=="ensemble_mean") & (result.tech=="combined")].iloc[0]
        self.assertAlmostEqual(row.capacity_gw,4)
        self.assertAlmostEqual(row.capacity_coverage_pct,25)
        self.assertAlmostEqual(row.station_2050_days,25)

    def test_point_assignment_and_border_tie(self):
        ids=assign_countries(np.array([0.5,1,1.5,9,360.5]),np.array([0.5]*5),
                             [box(0,0,1,1),box(1,0,2,1)])
        np.testing.assert_array_equal(ids,[0,0,1,-1,0])

    def test_circle_area_is_linear_and_zero_is_zero(self):
        sizes=circle_area(np.array([0,1,4,10]),10)
        self.assertEqual(sizes[0],0)
        self.assertAlmostEqual(sizes[2]/sizes[1],4)


    def test_generated_data_and_figures(self):
        import json
        from pathlib import Path
        from PIL import Image
        from prepare_country_exposure import OUTPUT, write_json
        table_path = OUTPUT/"csv/country_map_metrics.csv"
        figure_config = OUTPUT/"figures/figure_config.json"
        if not table_path.exists() or not figure_config.exists():
            self.skipTest("Run data preparation and plotting for output validation")
        data = pd.read_csv(table_path)
        self.assertFalse(data.duplicated(["country","model","scenario","tech"]).any())
        self.assertEqual(set(data.model), {"BCC-CSM2-MR","CANESM5","MPI-ESM1-2-HR","MRI-ESM2-0","ensemble_mean"})
        self.assertTrue(data.station_2050_days.dropna().between(0,366).all())
        self.assertTrue(data.grid_2050_days.dropna().between(0,732).all())
        ensemble = data[data.model=="ensemble_mean"]
        keys=["country","scenario"]
        cap = ensemble.pivot(index=keys,columns="tech",values="capacity_gw")
        np.testing.assert_allclose(cap.combined,cap.wind+cap.solar,atol=1e-6,equal_nan=True)
        grid = ensemble.pivot(index=keys,columns="tech",values="grid_2050_days")
        np.testing.assert_allclose(grid.combined,grid.wind+grid.solar,atol=1e-6,equal_nan=True)
        focus=["CHN","USA","IND","DEU","ZAF","AUS","RUS","BRA"]
        for iso in focus:
            rows=ensemble[ensemble.country_iso3==iso]
            self.assertEqual(len(rows),9)
            self.assertTrue(rows[["grid_2030_days","grid_2050_days","station_2050_days","capacity_gw"]].notna().all().all())
        checks=[]
        receipts=sorted((OUTPUT/"cache").glob("*/*.json"))
        self.assertEqual(len(receipts),24)
        for receipt in receipts:
            metadata=json.loads(receipt.read_text())
            for check in metadata["raw_station_checks"]:
                np.testing.assert_allclose(check["raw_days"],check["cache_days"],atol=2e-5,equal_nan=True)
                checks.append(check)
        config=json.loads(figure_config.read_text())
        self.assertEqual(len(config["figures"]),4)
        dimensions={}
        for path in config["figures"]:
            with Image.open(path) as picture:
                self.assertEqual(picture.format,"PNG")
                self.assertEqual(picture.width,4320)
                dimensions[Path(path).name]=picture.size
                preview=picture.copy()
                preview.thumbnail((1800,1800))
                preview_dir=OUTPUT/"qa"
                preview_dir.mkdir(exist_ok=True)
                preview.save(preview_dir/(Path(path).stem+"_preview.png"))
        capacity=ensemble.groupby(["scenario","tech"]).capacity_gw.sum()
        unassigned=ensemble[ensemble.country=="UNASSIGNED"].set_index(["scenario","tech"]).capacity_gw
        coverage=ensemble[(ensemble.capacity_gw>0)&(ensemble.country!="UNASSIGNED")].capacity_coverage_pct
        report={"table_rows":len(data),"ensemble_rows":len(ensemble),
                "mapped_countries":ensemble[ensemble.country!="UNASSIGNED"].country.nunique(),
                "cache_groups":len(receipts),"raw_station_decade_checks":len(checks),
                "raw_station_annual_checks":sum(len(c["years"]) for c in checks),
                "focus_country_iso3":focus,"focus_country_panels_complete":True,
                "unassigned_capacity_pct":{str(k):float(v) for k,v in (100*unassigned/capacity).items()},
                "country_capacity_coverage_pct_min":float(coverage.min()),
                "country_capacity_coverage_pct_median":float(coverage.median()),
                "figure_dimensions":dimensions}
        write_json(OUTPUT/"qa/validation.json",report)
        print(json.dumps(report,indent=2),flush=True)


if __name__=="__main__":
    unittest.main(verbosity=2)
