"""Scientific invariant and missing-data regression checks."""
import unittest
import tempfile
import json
import multiprocessing
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import pandas as pd
import xarray as xr
from paper_figures.config import LOSS_VARIABLES
from paper_figures.prepare.prepare_loss_tables import initialize_worker,read_year_worker
import numpy as np
from paper_figures.common.metrics import climate_deployment,three_factor,safe_ratio

class PreparationTests(unittest.TestCase):
    def test_spawn_reader_preserves_negative_losses_and_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'loss.nc'
            identity=dict(model='test',tech='wind')
            data={'capacity_mw':('station',[20.,10.]),'lon':('station',[1.,2.]),'lat':('station',[3.,4.])}
            for e in ['all','icing']:
                for key,prefix in LOSS_VARIABLES.items():
                    values=[-2.,3.] if key=='net_mwh' else [4.,5.]
                    data[prefix+'_'+e]=('station',values)
            ds=xr.Dataset(data,coords={'station_id':('station',['b','a'])},attrs={**identity,'supported_events':json.dumps(['icing'])})
            ds.to_netcdf(path)
            catalogue=pd.DataFrame({'station_id':['a','b'],'capacity_mw':[10.,20.],'lon':[2.,1.],'lat':[4.,3.]}).set_index('station_id')
            with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn'),initializer=initialize_worker,initargs=(catalogue,['all','icing'])) as pool:
                results=list(pool.map(read_year_worker,[(i,[{'path':str(path),'station_batch':'batch'}],identity) for i in range(2)]))
            for key,(ids,cap,v) in results:
                self.assertEqual(ids.tolist(),['a','b']);np.testing.assert_allclose(cap,[10,20]);np.testing.assert_allclose(v[:,0,0],[3,-2])

    def test_completion_requires_declared_artifacts(self):
        from paper_figures.common.io import complete,require_complete
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);artifact=root/"panel.csv";artifact.write_text("value\n1\n")
            complete(root/"marker",artifact_paths=[artifact])
            require_complete(root/"marker")
            artifact.write_text("truncated")
            with self.assertRaises(ValueError):require_complete(root/"marker")
            with self.assertRaises(FileNotFoundError):complete(root/"missing",artifact_paths=[root/"absent"])

    def test_decomposition_closes_with_interaction(self):
        r={('ssp126','ssp126'):4,('ssp585','ssp126'):7,('ssp126','ssp585'):2,('ssp585','ssp585'):10}
        d=climate_deployment(r)
        self.assertEqual(d['Phi_C']+d['Phi_S'],d['D']);self.assertEqual(d['J'],5);self.assertEqual(d['closure'],0)
    def test_three_factor_signed_closure(self):
        a=[100,0.4,-0.1];b=[150,0.2,0.3]
        self.assertAlmostEqual(three_factor(a,b).sum(),np.prod(b)-np.prod(a))
    def test_missing_and_zero_capacity(self):
        r=safe_ratio([0,3,-2],[1,0,2]);self.assertEqual(r[0],0);self.assertTrue(np.isnan(r[1]));self.assertEqual(r[2],-1)
    def test_ratio_of_totals(self):
        self.assertAlmostEqual(float(safe_ratio(10+20,1+10)),30/11)
    def test_undefined_factor_not_imputed(self):
        self.assertTrue(np.isnan(three_factor([0,np.nan,np.nan],[2,.3,.2])).all())
if __name__=='__main__':unittest.main()
