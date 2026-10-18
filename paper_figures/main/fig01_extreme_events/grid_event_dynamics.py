"""Streaming run statistics on observed event flags; no work on import."""
import numpy as np

STAT_NAMES = ("observed_steps", "known_starts", "complete_count", "complete_steps",
              "censored_count", "censored_steps", "max_complete_steps",
              "complete_ge24h", "complete_ge72h", "annual_max_observed_steps_sum")

class Runs:
    def __init__(self, ne, nc, area, region_ids, nr, max_steps):
        self.stats = np.zeros((len(STAT_NAMES), ne, nc), dtype=np.int64)
        self.length = np.zeros((ne, nc), dtype=np.int32)
        self.known = np.zeros((ne, nc), dtype=bool)
        self.previous_valid = np.zeros(nc, dtype=bool)
        self.annual_length = np.zeros((ne, nc), dtype=np.int32)
        self.annual_max = np.zeros((ne, nc), dtype=np.int32)
        self.hist = np.zeros((ne, nr, max_steps + 1), dtype=np.float64)
        self.area, self.region_ids = area, region_ids

    def close(self, e, cells, lengths, complete):
        if not len(cells):
            return
        nc = self.stats.shape[2]
        for full, count_index, sum_index in ((True, 2, 3), (False, 4, 5)):
            pick = complete if full else ~complete
            ix, dd = cells[pick], lengths[pick]
            self.stats[count_index, e] += np.bincount(ix, minlength=nc)
            self.stats[sum_index, e] += np.bincount(ix, weights=dd, minlength=nc).astype(np.int64)
            if full:
                np.maximum.at(self.stats[6, e], ix, dd)
                self.stats[7, e] += np.bincount(ix[dd >= 8], minlength=nc)
                self.stats[8, e] += np.bincount(ix[dd >= 24], minlength=nc)
                for ids in self.region_ids:
                    np.add.at(self.hist[e], (ids[ix], dd), self.area[ix])

    def consume(self, flags, valid):
        # Arrays are event x time x cell and time x cell, on a shared validity mask.
        for e, values in enumerate(flags):
            f = np.ascontiguousarray(values.T & valid.T)
            v = valid.T
            self.stats[0, e] += f.sum(axis=1)
            ended = np.flatnonzero((self.length[e] > 0) & ~f[:, 0])
            self.close(e, ended, self.length[e, ended],
                       self.known[e, ended] & valid[0, ended])
            self.length[e, ended] = 0
            starts = f.copy()
            starts[:, 1:] &= ~f[:, :-1]
            ends = f.copy()
            ends[:, :-1] &= ~f[:, 1:]
            ci, st = np.nonzero(starts)
            ce, en = np.nonzero(ends)
            if not np.array_equal(ci, ce):
                raise ValueError("Unpaired observed event fragments")
            duration = (en - st + 1).astype(np.int32)
            carry = (st == 0) & (self.length[e, ci] > 0)
            left_known = np.where(st == 0, self.previous_valid[ci], v[ci, np.maximum(st - 1, 0)])
            left_known[carry] = self.known[e, ci[carry]]
            duration[carry] += self.length[e, ci[carry]]
            new_known = left_known & ~carry
            self.stats[1, e] += np.bincount(ci[new_known], minlength=f.shape[0])
            inside = en < f.shape[1] - 1
            self.close(e, ci[inside], duration[inside],
                       left_known[inside] & v[ci[inside], en[inside] + 1])
            self.length[e] = 0
            self.known[e] = False
            tail = ~inside
            self.length[e, ci[tail]] = duration[tail]
            self.known[e, ci[tail]] = left_known[tail]
            annual_duration = en - st + 1
            prefix = st == 0
            annual_duration[prefix] += self.annual_length[e, ci[prefix]]
            np.maximum.at(self.annual_max[e], ci, annual_duration)
            self.annual_length[e] = 0
            self.annual_length[e, ci[tail]] = annual_duration[tail]
        self.previous_valid = valid[-1].copy()

    def finish_year(self):
        self.stats[9] += self.annual_max
        self.annual_max[:] = 0
        self.annual_length[:] = 0

    def finish(self):
        for e in range(self.length.shape[0]):
            ci = np.flatnonzero(self.length[e] > 0)
            self.close(e, ci, self.length[e, ci], np.zeros(len(ci), dtype=bool))
        self.length[:] = 0
        if not np.array_equal(self.stats[0], self.stats[3] + self.stats[5]):
            raise ValueError("Complete + censored durations do not reproduce observed exposure")


class FastRuns(Runs):
    """The same state and censoring contract, using the compiled streaming loop."""
    def __init__(self, ne, nc, area, region_ids, nr, max_steps, library):
        super().__init__(ne,nc,area,region_ids,nr,max_steps)
        import ctypes
        self._ctypes=ctypes
        self._library=ctypes.CDLL(str(library))
        self._accumulate=self._library.accumulate
        self._accumulate.argtypes=[ctypes.c_int]*6+[ctypes.c_void_p]*13
        self._accumulate.restype=None
        self.area=np.ascontiguousarray(area,dtype="f8")
        self.region_ids=np.ascontiguousarray(region_ids,dtype="i8")

    def consume(self, flags, valid):
        f=np.ascontiguousarray(flags,dtype="u1")
        v=np.ascontiguousarray(valid,dtype="u1")
        ne,nt,nc=f.shape;nr=self.hist.shape[1]
        if v.shape!=(nt,nc) or self.length.shape!=(ne,nc):
            raise ValueError("Streaming kernel shape mismatch")
        affected=np.zeros((nt,ne,nr),dtype="f8")
        valid_area=np.zeros((nt,nr),dtype="f8")
        arrays=[f,v,self.area,self.region_ids,self.stats,self.length,self.known,
                self.previous_valid,self.annual_length,self.annual_max,self.hist,affected,valid_area]
        self._accumulate(nt,nc,ne,nr,self.hist.shape[2],self.region_ids.shape[0],
                        *[self._ctypes.c_void_p(a.ctypes.data) for a in arrays])
        return affected,valid_area


def build_kernel(output_root):
    import fcntl
    import hashlib
    import subprocess
    from pathlib import Path
    source=Path(__file__).with_name("grid_event_dynamics.c")
    folder=Path(output_root)/"kernel"
    folder.mkdir(parents=True,exist_ok=True)
    fingerprint=hashlib.sha256(source.read_bytes()).hexdigest()
    target=folder/(fingerprint+".so")
    with (folder/"build.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not target.exists():
            temp=target.with_suffix(".tmp.so")
            subprocess.run(["gcc","-O3","-std=c99","-shared","-fPIC",str(source),"-o",str(temp)],check=True)
            temp.replace(target)
    return target
