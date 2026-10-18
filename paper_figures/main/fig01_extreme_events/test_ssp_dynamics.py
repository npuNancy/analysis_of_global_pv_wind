"""Independent checks for run counting, censoring and streamed chunk boundaries."""
import unittest
import numpy as np
from .grid_event_dynamics import Runs

def reference(flag, valid, year_length):
    out=np.zeros(10,dtype=np.int64); durations=[]
    n=0; known=False; prior=False; year_n=year_max=0
    for i,(f,v) in enumerate(zip(flag,valid)):
        active=bool(f and v)
        out[0]+=active
        if active:
            if not n:
                known=prior
                out[1]+=known
            n+=1
        elif n:
            if known and v:
                out[2]+=1;out[3]+=n;out[6]=max(out[6],n)
                out[7]+=n>=8;out[8]+=n>=24;durations.append(n)
            else:out[4]+=1;out[5]+=n
            n=0
        prior=bool(v)
        year_n=year_n+1 if active else 0
        year_max=max(year_max,year_n)
        if (i+1)%year_length==0:
            out[9]+=year_max;year_n=year_max=0
    if n:out[4]+=1;out[5]+=n
    return out,durations

class TestRuns(unittest.TestCase):
    def test_random_chunk_invariance(self):
        rng=np.random.default_rng(731)
        flags=rng.random((3,80,6))<.4
        valid=rng.random((80,6))>.12
        flags[0]=np.logical_or.reduce(flags[1:])
        area=np.arange(1,7,dtype=float)
        ids=np.stack([np.zeros(6,dtype=int),np.array([1,1,1,2,2,2])])
        expected=np.zeros((10,3,6),dtype="i8")
        hist=np.zeros((3,3,81))
        for e in range(3):
            for c in range(6):
                expected[:,e,c],d=reference(flags[e,:,c],valid[:,c],20)
                for n in d:
                    hist[e,0,n]+=area[c];hist[e,ids[1,c],n]+=area[c]
        for block in (1,3,7,20):
            r=Runs(3,6,area,ids,3,80)
            for year in range(4):
                for start in range(year*20,(year+1)*20,block):
                    stop=min(start+block,(year+1)*20)
                    r.consume(flags[:,start:stop],valid[start:stop])
                r.finish_year()
            r.finish()
            np.testing.assert_array_equal(r.stats,expected)
            np.testing.assert_allclose(r.hist,hist)


    def test_compiled_kernel_matches_reference(self):
        import tempfile
        from .grid_event_dynamics import FastRuns, build_kernel
        rng=np.random.default_rng(174)
        flags=rng.random((3,160,9))<.6
        flags[0]=flags[1]|flags[2]
        valid=rng.random((160,9))>.08
        area=rng.uniform(1,10,9)
        ids=np.stack([np.zeros(9,dtype=int),np.repeat([1,2,3],3)])
        with tempfile.TemporaryDirectory() as tmp:
            library=build_kernel(tmp)
            slow=Runs(3,9,area,ids,4,160)
            fast=FastRuns(3,9,area,ids,4,160,library)
            for year in range(4):
                for start in range(year*40,(year+1)*40,7):
                    stop=min(start+7,(year+1)*40)
                    f=flags[:,start:stop];v=valid[start:stop]
                    slow.consume(f,v);affected,available=fast.consume(f,v)
                    for ri in range(4):
                        cells=np.any(ids==ri,axis=0)
                        expected=f[:,:,cells]&v[:,cells][None]
                        np.testing.assert_allclose(affected[:,:,ri],(expected*area[cells]).sum(axis=2).T,rtol=1e-12)
                        np.testing.assert_allclose(available[:,ri],(v[:,cells]*area[cells]).sum(axis=1),rtol=1e-12)
                slow.finish_year();fast.finish_year()
            slow.finish();fast.finish()
            np.testing.assert_array_equal(slow.stats,fast.stats)
            np.testing.assert_allclose(slow.hist,fast.hist,rtol=1e-12)

    def test_long_duration_and_spatial_reduction(self):
        from .summarize_ssp_dynamics import longest_observed, pooled_p90
        f=np.r_[False,np.ones(30,dtype=bool),False][None,:,None]
        v=np.ones((32,1),bool)
        r=Runs(1,1,np.array([2.]),np.zeros((1,1),int),1,32)
        r.consume(f[:,:11],v[:11]);r.consume(f[:,11:],v[11:])
        r.finish_year();r.finish()
        self.assertEqual(r.stats[7,0,0],1)
        self.assertEqual(r.stats[8,0,0],1)
        self.assertEqual(pooled_p90(r.hist[0,0]),90)
        self.assertEqual(longest_observed(f[0,:,0]),90)
        # Patch P95 values cannot be averaged: opposite-time footprints cancel.
        a=np.array([0.,0.,100.,100.]);b=100-a
        self.assertNotEqual(np.quantile((a+b)/2,.95),(np.quantile(a,.95)+np.quantile(b,.95))/2)

    def test_union_handoff_and_missing(self):
        f=np.array([[0,1,1,0,0,0],[0,0,0,1,1,0]],dtype=bool)[:,:,None]
        f=np.concatenate([np.logical_or.reduce(f)[None],f])
        v=np.ones((6,1),dtype=bool)
        r=Runs(3,1,np.ones(1),np.zeros((1,1),int),1,6)
        r.consume(f[:,:3],v[:3]);r.consume(f[:,3:],v[3:]);r.finish_year();r.finish()
        self.assertEqual(r.stats[2,0,0],1)
        self.assertEqual(r.stats[3,0,0],4)
        self.assertEqual(r.stats[6,0,0],4)
        self.assertEqual(r.stats[2,1:,0].sum(),2)
        v[2]=False
        r=Runs(3,1,np.ones(1),np.zeros((1,1),int),1,6)
        r.consume(f,v);r.finish_year();r.finish()
        self.assertEqual(r.stats[2,0,0],0)
        self.assertEqual(r.stats[4,0,0],2)
        self.assertEqual(r.stats[5,0,0],3)

if __name__=="__main__":
    unittest.main()
