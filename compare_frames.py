"""Diff two shade models, because the six named streets in tests/validate.py
cannot tell you what a change did.

They sit in shade's insensitive majority: a change that wrecks one street in
seventeen passes them clean. So when you touch the model, keep the old
build/frames.npy and diff it against the new one.

    cp build/frames.npy before.npy
    ...change something, make...
    python compare_frames.py before.npy build/frames.npy

Shade is stored as one byte per segment per frame, already in percent, so a
difference is in percentage points with no conversion. The same tool measures
the sensitivity probe: build with OMBRA_JITTER=<seed> set, and the diff against
an ordinary build is how much of the map rests on estimated heights.

If two runs you expected to differ come out 100 % identical, suspect the build
before the model. Every stage reads what the last one left in build/, and none
of them checks that it is fresh: a build_dsm.py that died half way leaves the
previous dsm.npy in place, and shade.py will happily re-derive the same frames
from it. That is exactly how this file first reported "no sensitivity at all".
"""
import sys, numpy as np

if len(sys.argv) != 3:
    print(__doc__)
    raise SystemExit(2)

a = np.load(sys.argv[1]).astype(np.int16)
b = np.load(sys.argv[2]).astype(np.int16)
if a.shape != b.shape:
    print(f"different shapes: {a.shape} vs {b.shape} -- the segments moved, "
          f"so these two are not comparable")
    raise SystemExit(1)

d = np.abs(b - a).ravel()
n = d.size
print(f"{sys.argv[1]}  ->  {sys.argv[2]}")
print(f"{n:,} segment-frames   ({a.shape[0]} frames x {a.shape[1]} segments)")
print()
print(f"  identical            {100*(d == 0).mean():6.2f} %")
for t in (1, 5, 10, 20):
    print(f"  moved by more than {t:>2} pp  {100*(d > t).mean():6.2f} %")
print()
print(f"  city mean            {a.mean():.2f} -> {b.mean():.2f}  "
      f"({b.mean()-a.mean():+.2f} pp)")
print(f"  mean absolute move   {d.mean():.2f} pp")
moved = d[d > 0]
if moved.size:
    print(f"  where it moved       median {np.median(moved):.0f} pp, "
          f"p90 {np.percentile(moved, 90):.0f} pp, max {moved.max()} pp")

# Per-segment, because a street you can name is what a reader will check.
seg = np.abs(b.astype(np.int32) - a).mean(axis=0)
print()
print(f"  segments {len(seg):,}: {100*(seg == 0).mean():.1f} % untouched, "
      f"{100*(seg > 10).mean():.1f} % move by more than 10 pp on average")
