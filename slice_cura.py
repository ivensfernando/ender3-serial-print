#!/usr/bin/env python3
"""Slice an STL for the Ender-3 V3 SE with CuraEngine and wrap it in the start/end
gcode that already printed fine on this printer (see README.md). Usage:

    slice_cura.py part.stl out.gcode [brim_mm]

Prints bounding box, layer count and the estimated time. Refuses to write a file
whose moves leave the 220x220x250 bed.
"""
import os, re, subprocess, sys

DEFS = "/usr/share/cura/resources/definitions"
START = """M201 X2500 Y2500 Z500 E5000
M203 X250 Y250 Z5 E40
M204 P2500 R500 T2500
M205 X10.00 Y10.00 Z0.40 E5.00
M205 J0.100
M220 S100
M221 S100
M104 S205 ;Set final nozzle temp
M190 S60 ;Set and wait for bed temp to stabilize
G28 ;Home
G92 E0 ;Reset Extruder
G1 Z2.0 F3000 ;Move Z Axis up
G1 X-2.1 Y20 Z0.28 F5000.0 ;Move to start position
M109 S205 ;Wait for nozzle temp to stabilize
G4 S60 ;let the melt zone soak before pushing plastic
G1 E8 F120 ;slow prime
G92 E0
G1 X-2.1 Y145.0 Z0.28 F1500.0 E15 ;Draw the first line
G1 X-2.4 Y145.0 Z0.28 F5000.0 ;Move to side a little
G1 X-2.4 Y20 Z0.28 F1500.0 E30 ;Draw the second line
G92 E0 ;Reset Extruder
G1 E-1.0000 F1800 ;Retract a bit
G1 Z2.0 F3000 ;Move Z Axis up
G1 E0.0000 F1800
G90
G21
M82 ;absolute extrusion
M106 S0
G92 E0
"""
START_RESUME = """M201 X2500 Y2500 Z500 E5000
M203 X250 Y250 Z5 E40
M204 P2500 R500 T2500
M205 X10.00 Y10.00 Z0.40 E5.00
M205 J0.100
M220 S100
M221 S100
G90
M82 ;absolute extrusion
G92 E0
G1 Z60 F600 ;NO full G28: the part sits where the Z probe homes. Go straight up first,
G28 X Y ;re-home X and Y only (no probe): the steppers time out when idle and the head can slide, as happened
G1 X-2.1 Y20 F4000 ;then away to the left edge, clear of the part
M104 S205 ;Set final nozzle temp
M190 S60 ;Set and wait for bed temp to stabilize
M109 S205 ;Wait for nozzle temp to stabilize
G4 S60 ;let the melt zone soak before pushing plastic
G1 E8 F120 ;slow prime
G92 E0
G1 Z0.28 F1000 ;purge line at the left edge, nowhere near the part
G1 X-2.1 Y145.0 Z0.28 F1500.0 E15 ;Draw the first line
G1 X-2.4 Y145.0 Z0.28 F5000.0 ;Move to side a little
G1 X-2.4 Y20 Z0.28 F1500.0 E30 ;Draw the second line
G92 E0 ;Reset Extruder
G1 E-1.0000 F1800 ;Retract a bit
G1 Z2.0 F3000 ;Move Z Axis up
G1 E0.0000 F1800
G90
G21
M82 ;absolute extrusion
M106 S0
G92 E0
"""
END = """G91 ;Relative positionning
G1 E-2 F2700 ;Retract a bit
G1 E-2 Z0.2 F2400 ;Retract and raise Z
G1 X5 Y5 F3000 ;Wipe out
G1 Z10 ;Raise Z more
G90 ;Absolute positionning
G1 X0 Y220 ;Present print
M106 S0 ;Turn-off fan
M104 S0 ;Turn-off hotend
M140 S0 ;Turn-off bed
M84 X Y E ;Disable all steppers but Z
"""

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("stl"); ap.add_argument("out")
    ap.add_argument("brim", nargs="?", default="5")
    ap.add_argument("--layer", type=float, default=0.28)
    ap.add_argument("--infill", type=float, default=5)
    ap.add_argument("--walls", type=float, default=1.2, help="wall thickness in mm")
    ap.add_argument("--speed", type=float, default=60)
    ap.add_argument("--nozzle", type=int, default=200, help="printing nozzle temperature (first layer +5)")
    ap.add_argument("--bed", type=int, default=60)
    ap.add_argument("--fan", type=int, default=100, help="part cooling fan, percent")
    ap.add_argument("--top-pattern", choices=["lines", "concentric", "zigzag"], default="lines",
                    help="pattern of the top (and bottom) skin; concentric follows the outline inwards, no diagonal lines")
    ap.add_argument("--bottom-pattern", choices=["lines", "concentric", "zigzag"], default="lines",
                    help="pattern of the first layer (the face that touches the bed); concentric looks better on a visible face")
    ap.add_argument("--support", choices=["none", "buildplate", "everywhere"], default="none",
                    help="slicer-generated, breakaway supports (buildplate = only from the bed, everywhere = also from the part)")
    ap.add_argument("--support-density", type=float, default=12, help="support infill percent (lower = thinner, easier to break)")
    ap.add_argument("--support-walls", type=int, default=1, help="outline walls around each support (0 = none, thinnest)")
    ap.add_argument("--support-pattern", choices=["lines", "grid", "zigzag", "triangles"], default="lines", help="support pattern; grid supports both directions")
    ap.add_argument("--resume-layer", type=int, default=None,
                    help="continue a stopped print: skip layers below N, keep the part where it is on the bed")
    a = ap.parse_args()
    stl, out, brim = a.stl, a.out, a.brim
    raw = out + ".cura"
    s = {
        "machine_width": 220, "machine_depth": 220, "machine_height": 250,
        "machine_center_is_zero": "false", "machine_nozzle_size": 0.4,
        "machine_start_gcode": "", "machine_end_gcode": "",
        "layer_height": a.layer, "layer_height_0": 0.32, "initial_layer_line_width_factor": 115,
        "wall_thickness": a.walls, "top_bottom_thickness": 1.2,
        "infill_sparse_density": a.infill, "infill_pattern": "grid",
        "support_enable": "false", "adhesion_type": "brim", "brim_width": brim,
        "speed_print": a.speed, "speed_wall_0": min(a.speed, 45), "speed_wall_x": a.speed, "speed_infill": a.speed*1.3,
        "speed_topbottom": 40, "speed_layer_0": 20, "speed_travel": 150,
        "acceleration_enabled": "false", "jerk_enabled": "false",
        "retraction_enable": "true", "retraction_amount": 1.6, "retraction_retract_speed": 45, "retraction_prime_speed": 35,
        "material_print_temperature": a.nozzle, "material_print_temperature_layer_0": a.nozzle + 5,
        "material_bed_temperature": a.bed, "material_bed_temperature_layer_0": a.bed,
        "cool_fan_enabled": "true" if a.fan > 0 else "false", "cool_fan_speed": a.fan, "cool_fan_full_layer": 3,
        "material_diameter": 1.75, "machine_gcode_flavor": "RepRap (Marlin/Sprinter)",
    }
    # the engine ignores the front-end's density/thickness settings; it wants these:
    s["infill_line_distance"] = 0 if a.infill <= 0 else round(0.4 * 100 / a.infill * 2, 2)   # grid
    s["wall_line_count"] = max(1, round(a.walls / 0.4))
    if a.support != "none":
        s.update({"support_enable": "true", "support_type": a.support, "support_angle": 50, "support_infill_rate": a.support_density, "support_wall_count": a.support_walls, "support_line_distance": round(0.4 * 100 / a.support_density, 2),
                  "support_pattern": a.support_pattern, "support_z_distance": 0.28, "support_xy_distance": 0.8,
                  "support_interface_enable": "true", "support_roof_enable": "true"})
    s["top_bottom_pattern_0"] = a.bottom_pattern
    s["top_bottom_pattern"] = a.top_pattern          # the first layer keeps its own pattern (top_bottom_pattern_0, lines)
    s["top_layers"] = s["bottom_layers"] = max(2, round(1.2 / a.layer))
    start_txt = START_RESUME if a.resume_layer is not None else START
    start_txt = (start_txt.replace("M104 S205", "M104 S%d" % (a.nozzle + 5)).replace("M109 S205", "M109 S%d" % (a.nozzle + 5))
                 .replace("M190 S60", "M190 S%d" % a.bed))
    cmd = ["CuraEngine", "slice", "-j", f"{DEFS}/creality_ender3.def.json", "-o", raw]
    for k, v in s.items():
        cmd += ["-s", f"{k}={v}"]
    cmd += ["-e0"]
    xs, ys = [], []
    for l in open(stl, errors="replace"):
        l = l.strip()
        if l.startswith("vertex"):
            _, x, y, _z = l.split(); xs.append(float(x)); ys.append(float(y))
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2     # CuraEngine puts the STL origin, not its centre, at the bed centre
    cmd += ["-l", stl, "-s", f"mesh_position_x={-cx}", "-s", f"mesh_position_y={-cy}"]
    env = dict(os.environ, CURA_ENGINE_SEARCH_PATH=f"{DEFS}:/usr/share/cura/resources/extruders")
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if not os.path.exists(raw) or os.path.getsize(raw) < 1000:
        print(r.stdout[-2000:], r.stderr[-2000:]); sys.exit("slice failed")
    body = open(raw).read()
    resume_pre = ""
    if a.resume_layer is not None:
        marker = ";LAYER:%d\n" % a.resume_layer
        cut = body.index(marker)
        e = 0.0
        for l in body[:cut].splitlines():
            c = l.split(";")[0].strip()
            m = re.match(r"G92 E(-?[\d.]+)", c)
            if m: e = float(m.group(1)); continue
            m = re.search(r" E(-?[\d.]+)", c)
            if c.startswith(("G0", "G1")) and m: e = float(m.group(1))
        before = body[:cut].splitlines()
        # Cura already did the layer-change travel (with the new Z) before the marker: keep every
        # non-extruding move from the last Z move up to the marker, otherwise the first line would
        # extrude from the wrong place.
        tail = []
        for l in reversed(before):
            c = l.split(";")[0].strip()
            if not c: continue
            if c.startswith(("G0", "G1")) and " E" in c and "Z" not in c:
                if tail: break            # reached an extruding move before any travel
                continue
            tail.append(c)
            if c.startswith(("G0", "G1")) and "Z" in c: break
        tail.reverse()
        # travel 0.6 mm above the layer (the top of the stopped part is at the layer height itself,
        # and may carry tape), then come down just before extruding
        zlayer = None
        for i, c in enumerate(tail):
            m = re.search(r"Z(-?[\d.]+)", c)
            if m:
                zlayer = float(m.group(1)); tail[i] = c.replace("Z" + m.group(1), "Z%.2f" % (zlayer + 0.6))
        tail.append("G1 Z%.2f F600 ;down to the layer height" % zlayer)
        print("kept before the marker:", tail)
        body = "\n".join(tail) + "\n" + body[cut:]
        resume_pre = ("G1 Z40 F3000 ;lift well above the part before travelling over it\n"
                      "M104 S%d ;printing temperature\nM106 S%d ;fan\nG92 E%.5f ;E counter as at the end of layer %d\n"
                      % (int(float(s["material_print_temperature"])), int(a.fan*255/100), e, a.resume_layer - 1))
    # keep only motion, extrusion and fan; drop Cura's own header/temps/homing
    lines = []
    time = None
    for l in body.splitlines():
        if l.startswith(";TIME_ELAPSED:"): time = int(float(l.split(":")[1]))   # last one = total
        if l.startswith(("M104", "M109", "M140", "M190", "G28", "M84", "M107 ;", "M82", "M83")) and not lines:
            continue
        lines.append(l)
    xs, ys, zs = [], [], []
    for l in lines:
        if l.startswith(("G0", "G1")):
            for ax, arr in (("X", xs), ("Y", ys), ("Z", zs)):
                m = re.search(ax + r"(-?\d+\.?\d*)", l)
                if m: arr.append(float(m.group(1)))
    bb = (min(xs), max(xs), min(ys), max(ys), max(zs))
    print("bbox X %.1f..%.1f  Y %.1f..%.1f  Zmax %.2f" % bb)
    if bb[0] < 0 or bb[1] > 220 or bb[2] < 0 or bb[3] > 220 or bb[4] > 250:
        sys.exit("REFUSED: moves outside the bed")
    with open(out, "w") as f:
        f.write(";sliced by CuraEngine via slice_cura.py\n" + start_txt + resume_pre + "\n".join(lines) + "\n" + END)
    os.remove(raw)
    print("time ~%s min, %d lines -> %s" % (time // 60 if time else "?", len(lines), out))

main()
