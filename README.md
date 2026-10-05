# ender3-serial-print

Print on a Creality Ender-3 V3 SE (Marlin 1.0.6) straight from a Linux PC over its USB-C serial port: slice an STL with
CuraEngine, stream the G-code line by line, pause, stop and change settings while it runs. Small Python scripts, no server.

- `slice_cura.py`: wraps CuraEngine 4.13 (start/end G-code for this printer, ABS and PLA options, supports, concentric top).
- `send_gcode.py`: streams G-code over `/dev/ttyUSB0` at 115200 baud, waits for `ok`, stops on errors.
- `check_overhang.py`: reports how much of an STL would need support.
- `README.md` (this file): the print procedure, step by step.
- `COMO-FUNCIONA.md`: how it works, what went wrong, and whether a desktop program is worth writing (in Portuguese).

Requirements: Python 3 with `pyserial`, CuraEngine (the Cura definitions are expected in `/usr/share/cura/resources/definitions`),
and your user in the `dialout` group.

**Use at your own risk.** The G-code start/end blocks, bed-leveling mesh and Z-probe offset in `slice_cura.py` are tuned for one
machine. Check them against your printer, and never leave a print unattended. Printing from a PC needs the PC awake for the
whole print. The firmware, not these scripts, protects against thermal runaway.

---

# Printing on the Ender-3 V3 SE from this PC (serial)

How a print was actually done here on 2026-09-30, written so another agent can
repeat it. Verified end to end: two PLA parts (`fitplate`, `plate_trim`) printed
with the replacement CR-Touch.

## Setup facts (do not re-discover)

- The printer's **USB-C port is a serial link to the PC**, not a storage host.
  It shows up as `/dev/ttyUSB0` (CH340, `1a86:7523`), 115200 baud, Marlin 1.0.6
  (`M115` → `MACHINE_TYPE:Ender-3 V3 SE`).
- Because of that, `M21`/`M20` answer `No SD card` / `No media`. That is
  expected when the gcode card sits in a USB-C card reader: the reader is
  plugged into the **PC**, not the printer. It mounts under
  `/media/$USER/<label>` (was `0403-0201`, FAT32). Find it with `lsblk`.
- To print from the card the normal way, put the microSD in the printer's own
  slot instead. To print from the PC, stream over serial (below).
- Opening the port does not reset the board (axes stay homed).
- The user is in the `dialout` group only in new sessions. Run serial commands
  through `sg dialout -c '...'`.

## Print procedure

1. Check the printer answers and is idle (read-only):
   `M115`, `M105`, `M27` (expect `Not SD printing`), `M119`.
2. Check the probe (no axis movement): `M401` (deploy) then `M119`, then `M402`
   (stow) then `M119`.
   - Healthy CR-Touch on this Marlin: **deployed → `z_min: open`,
     stowed → `z_min: TRIGGERED`**. `TRIGGERED` at rest is normal.
   - A dead probe stays frozen at one value (the old one did).
3. Check leveling: `M420 V` prints the 4×4 bilinear mesh, `M851` prints the
   probe offset (`Z-1.36` is the known-good value).
4. Ask the user to confirm: bed clean, PLA loaded, PC stays on and connected
   for the whole print.
5. Start in the background so the shell is not blocked:
   ```bash
   sg dialout -c "nohup python3 send_gcode.py \
     /media/$USER/<label>/fitplate_PLA_31m37s.gcode >/tmp/print.out 2>&1 &"
   tail /tmp/print.log
   ```
6. Monitor with `tail /tmp/print.log`. The log shows `N/total` lines and the
   position (`Z`) after each layer change (`G92 E0`).
7. It ends with `DONE`; the gcode itself turns the heaters off. Confirm with
   `M105` (targets `/0.00`).

Stop early: `touch /tmp/print.stop` (script turns heaters off and exits).
Emergency: cut printer power.

## What the gcode does (Orca, PLA)

`M104 S220`, `M190 S55`, `G28`, move to the left edge (`X-2.1 Y20 Z0.28`),
`M109 S220`, purge line (E15 then E30), then the part. `G28` does no leveling;
the stored mesh is used (`Bed Leveling ON`).

## Things that went wrong or looked wrong

- **Purge line looks like nothing is extruding.** The nozzle needs a few
  seconds to fill after `M109`. On the first attempt the print was aborted at
  this point because "nothing comes out"; a moment later it was extruding
  normally and the print had to be restarted from scratch. **Do not kill the
  job at the purge line. Ask the user to wait until the part starts.**
- **Long silent stretch after the purge start** is `M109` waiting for 220 °C
  (from ~140 °C takes a few minutes). The log filters temperature lines, so it
  appears stuck. It is not.
- **`pkill -f send_gcode` kills your own shell** (the pattern is in its own
  command line, exit 144). Find the PID with
  `ps -eo pid,cmd | grep "[s]end_gcode"` and `kill` it, or use the stop file.
- **Foreground `sleep N` is blocked** by the harness; use short checks or
  background jobs.
- After a manual abort: `M410` (quick stop), then `G91`, `G1 Z15 F600`, `G90`
  to lift the head. Axes stay homed. Restarting the gcode re-runs `G28` and
  the purge; the bed must be cleaned first.

## Time estimates

Slicer time (`;TIME:` in the header) is a rough lower bound. `fitplate`
estimated 31m37s and took ~34 min; `plate_trim` estimated 51m19s and took
~53 min. Lines-done / total lines is a better progress proxy than Z height,
because the first layers are slower.

## Files used

- `send_gcode.py` — the streamer (this folder).
- Sliced with OrcaSlicer 2.4.2: `fitplate_PLA_31m37s.gcode` (47 layers,
  9.4 mm, 33 247 lines), `plate_trim_PLA_51m19s.gcode` (197 layers, 39.4 mm,
  112 642 lines).
- Probe diagnosis and bench rig: `../cr_touch_bench_test/README.md`.
