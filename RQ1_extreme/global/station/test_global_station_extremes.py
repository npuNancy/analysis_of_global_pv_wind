"""Numerical and output checks for global station exposure."""
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from global_station_extremes import (OUTPUT, weighted_quantile, exposure_summary,
                                     transition_summary, TRANSITIONS, ensemble)


class GlobalStationTests(unittest.TestCase):
    def test_capacity_weighting_and_missingness(self):
        result=exposure_summary(np.array([10.,30.,np.nan]),np.array([1.,3.,6.]),20)
        self.assertAlmostEqual(result["exposure_days"],25)
        self.assertAlmostEqual(result["capacity_coverage_pct"],40)
        self.assertAlmostEqual(result["high_share_pct"],75)
        self.assertEqual(result["total_capacity_gw"],10)

    def test_weighted_p80_and_strict_ties(self):
        days=np.array([0.,0.,10.])
        capacity=np.array([4.,4.,2.])
        threshold=weighted_quantile(days,capacity)
        self.assertEqual(threshold,0)
        self.assertEqual(exposure_summary(days,capacity,threshold)["high_share_pct"],20)
        self.assertTrue(np.isnan(weighted_quantile(np.array([np.nan]),np.array([1.]))))

    def test_paired_transition_denominator(self):
        base=np.array([0.,0.,10.,10.,np.nan])
        future=np.array([0.,10.,10.,0.,20.])
        weights=np.array([1.,2.,3.,4.,10.])
        result=transition_summary(base,future,weights,5.)
        self.assertEqual([r["transition"] for r in result],list(TRANSITIONS))
        np.testing.assert_allclose([r["capacity_share_pct"] for r in result],[10,20,30,40])
        self.assertEqual(result[0]["paired_coverage_pct"],50)

    def test_ensemble_requires_complete_models(self):
        table=pd.DataFrame({"model":list("abcd"),"tech":["wind"]*4,"exposure_days":[1.,2.,3.,4.]})
        row=ensemble(table,["tech"]).iloc[0]
        self.assertEqual(row.exposure_days,2.5)
        self.assertEqual(row.exposure_days_min,1)
        self.assertEqual(row.exposure_days_max,4)
        table.loc[3,"exposure_days"]=np.nan
        self.assertTrue(np.isnan(ensemble(table,["tech"]).iloc[0].exposure_days))
        with self.assertRaises(ValueError):
            ensemble(table.iloc[:3],["tech"])

    def test_real_outputs(self):
        from PIL import Image
        csv=OUTPUT/"csv"
        if not (OUTPUT/"figures/figure_manifest.json").exists():
            self.skipTest("Full output validation follows the main job")
        expected={"annual":1104,"cohort":744,"thresholds":24,"transitions":192,"newbuild":72}
        for name,n in expected.items():
            data=pd.read_csv(csv/(name+"_by_model.csv"))
            self.assertEqual(len(data),n,name)
            if "exposure_days" in data:
                self.assertTrue(data.exposure_days.dropna().between(0,366).all(),name)
            if "capacity_coverage_pct" in data:
                self.assertTrue(data.capacity_coverage_pct.dropna().between(0,100+1e-8).all(),name)
        config=json.loads((OUTPUT/"run_config.json").read_text())
        annual=pd.read_csv(csv/"annual_by_model.csv")
        if config["capacity_policy"]=="snapshots":
            self.assertTrue(annual.loc[~annual.year.isin([2030,2040,2050]),["exposure_days","high_capacity_gw","total_capacity_gw"]].isna().all().all())
        self.assertTrue(annual.loc[annual.year.isin([2030,2040,2050]),"exposure_days"].notna().all())
        transitions=pd.read_csv(csv/"transitions_by_model.csv")
        totals=transitions.groupby(["model","scenario","tech","year"]).capacity_share_pct.sum()
        np.testing.assert_allclose(totals,100,atol=1e-8)
        thresholds=pd.read_csv(csv/"thresholds_by_model.csv")
        self.assertTrue(thresholds.threshold_days.notna().all())
        self.assertTrue((thresholds.high_share_pct<=20+1e-8).all())
        checks=json.loads((OUTPUT/"validation.json").read_text())
        self.assertEqual(checks["cache_groups"],24)
        self.assertEqual(checks["nonempty_combinations"],864)
        self.assertEqual(checks["empty_combinations"],264)
        self.assertEqual(checks["country_reconciliations"],24)
        self.assertEqual(checks["raw_annual_checks"],2208)
        manifest=json.loads((OUTPUT/"figures/figure_manifest.json").read_text())
        self.assertEqual(len(manifest["figures"]),5)
        for path in manifest["figures"]:
            with Image.open(path) as image:
                self.assertEqual(image.format,"PNG")
                self.assertEqual(image.size,(3750,2040))
        print(json.dumps(checks,indent=2),flush=True)


if __name__=="__main__":
    unittest.main(verbosity=2)
