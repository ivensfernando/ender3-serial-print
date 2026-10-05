#!/usr/bin/env python3
"""List how much surface of each STL (already in print orientation, bed at z=0) faces down more
steeply than 45 degrees without resting on the bed, i.e. what would need support.

    check_overhang.py stl/*.stl

Rule of thumb: a few tens of mm2 spread over small holes (blind dowel holes, hex sockets) are fine,
bridging is short. Hundreds of mm2 in one place, or any thin free-standing feature that starts in
mid-air (a point, a sliver, a horizontal rod) need another orientation or a separate part.
This does NOT catch features that start as a thin point in mid-air with sloped sides under 45 deg.
"""
import math, sys

def tris(f):
    vs = []
    for l in open(f, errors="replace"):
        l = l.strip()
        if l.startswith("vertex"):
            _, x, y, z = l.split(); vs.append((float(x), float(y), float(z)))
    return [vs[i:i + 3] for i in range(0, len(vs) - 2, 3)]

for f in sys.argv[1:]:
    bad = tot = 0.0; zs = []
    for a, b, c in tris(f):
        ux, uy, uz = b[0]-a[0], b[1]-a[1], b[2]-a[2]; vx, vy, vz = c[0]-a[0], c[1]-a[1], c[2]-a[2]
        nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        L = math.sqrt(nx*nx + ny*ny + nz*nz)
        if L < 1e-9: continue
        tot += L / 2; nz /= L
        if nz < -0.7071 and min(a[2], b[2], c[2]) > 0.3:
            bad += L / 2; zs.append((a[2] + b[2] + c[2]) / 3)
    print("%-26s overhang %7.1f mm2 of %8.0f (%.1f%%)  %s" % (f.split("/")[-1], bad, tot, 100*bad/tot,
          "z %.0f..%.0f mm" % (min(zs), max(zs)) if zs else ""))
