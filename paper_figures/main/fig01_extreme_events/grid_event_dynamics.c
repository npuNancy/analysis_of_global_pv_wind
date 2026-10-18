#include <stdint.h>
#include <stddef.h>

/* Arrays use C order. Runs are continuous across calls; all events share valid. */
void accumulate(int nt, int nc, int ne, int nr, int nh, int ng,
    const uint8_t *flags, const uint8_t *valid, const double *area,
    const int64_t *region, int64_t *stats, int32_t *length,
    uint8_t *known, uint8_t *previous_valid, int32_t *annual_length,
    int32_t *annual_max, double *hist, double *affected, double *valid_area) {
    const size_t plane = (size_t)ne * nc;
    for (int t=0;t<nt;t++) {
        for (int c=0;c<nc;c++) {
            const int v=valid[(size_t)t*nc+c] != 0;
            const int prior=previous_valid[c] != 0;
            const double w=area[c];
            if (v) {
                for (int g=0;g<ng;g++) {
                    int r=(int)region[(size_t)g*nc+c];
                    valid_area[(size_t)t*nr+r]+=w;
                }
            }
            for (int e=0;e<ne;e++) {
                size_t j=(size_t)e*nc+c;
                const int f=v && flags[((size_t)e*nt+t)*nc+c] != 0;
                int n=length[j];
                if (f) {
                    stats[j]++;
                    if (!n) {
                        known[j]=(uint8_t)prior;
                        stats[plane+j]+=prior;
                    }
                    length[j]=n+1;
                    int a=++annual_length[j];
                    if (a>annual_max[j]) annual_max[j]=a;
                    for (int g=0;g<ng;g++) {
                        int r=(int)region[(size_t)g*nc+c];
                        affected[((size_t)t*ne+e)*nr+r]+=w;
                    }
                } else {
                    if (n) {
                        if (known[j] && v) {
                            stats[2*plane+j]++;
                            stats[3*plane+j]+=n;
                            if (n>stats[6*plane+j]) stats[6*plane+j]=n;
                            stats[7*plane+j]+=(n>=8);
                            stats[8*plane+j]+=(n>=24);
                            for (int g=0;g<ng;g++) {
                                int r=(int)region[(size_t)g*nc+c];
                                hist[((size_t)e*nr+r)*nh+n]+=w;
                            }
                        } else {
                            stats[4*plane+j]++;
                            stats[5*plane+j]+=n;
                        }
                    }
                    length[j]=0;
                    known[j]=0;
                    annual_length[j]=0;
                }
            }
            previous_valid[c]=(uint8_t)v;
        }
    }
}
