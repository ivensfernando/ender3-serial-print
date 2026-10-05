#!/usr/bin/env python3
"""Stream a gcode file to a Marlin printer over serial, one line at a time.

Usage:  python3 send_gcode.py FILE.gcode [--port /dev/ttyUSB0] [--log /tmp/print.log]

Flow control is the printer's own `ok`: each line is sent only after the
previous one was acknowledged. Long blocking commands (G28, M109, M190) keep
the printer silent or sending `busy`/temperature reports, so the per-line
timeout is 15 min of *total silence*, reset by any received data.

Safety: on any line containing error/stop/kill/halt (or a timeout, or the
file /tmp/print.stop appearing) it turns the heaters and fan off and exits.
To stop a print cleanly:  touch /tmp/print.stop
To change something live (temperature, speed, flow): put the command in /tmp/print.cmd;
it is sent between two print lines. /tmp/print.idx holds the current line index.
"""
import argparse, os, re, sys, time
import serial

ap = argparse.ArgumentParser()
ap.add_argument("gcode")
ap.add_argument("--port", default="/dev/ttyUSB0")
ap.add_argument("--baud", type=int, default=115200)
ap.add_argument("--log", default="/tmp/print.log")
ap.add_argument("--stop-file", default="/tmp/print.stop")
ap.add_argument("--cmd-file", default="/tmp/print.cmd")
ap.add_argument("--idx-file", default="/tmp/print.idx")
a = ap.parse_args()

log_f = open(a.log, "w", buffering=1)
def log(m): log_f.write(time.strftime("%H:%M:%S ") + m + "\n")

lines = []
for l in open(a.gcode, errors="replace"):
    l = l.split(";")[0].strip()          # drop comments / blank lines
    if l:
        lines.append(l)
log(f"total {len(lines)} lines from {a.gcode}")

s = serial.Serial(a.port, a.baud, timeout=1)
time.sleep(1)                             # opening the port does NOT reset this board
s.reset_input_buffer()

def abort(why):
    log("ABORT: " + why)
    for c in ("M104 S0", "M140 S0", "M107"):
        s.write((c + "\n").encode()); time.sleep(0.3)
    sys.exit(1)

def send_now(cmd):
    """Send one command between print lines and wait for its own ok."""
    s.write((cmd + "\n").encode())
    while True:
        r = s.readline().decode(errors="replace").strip()
        if r.startswith("ok"):
            return
        if re.search(r"error|stop|kill|halt", r, re.I) and "busy" not in r:
            abort(r)

for i, l in enumerate(lines):
    if os.path.exists(a.stop_file):
        abort("stop file")
    if os.path.exists(a.cmd_file):        # live commands, e.g.  echo "M104 S208" > /tmp/print.cmd
        for c in open(a.cmd_file).read().split("\n"):
            c = c.split(";")[0].strip()
            if c:
                log("live command: " + c); send_now(c)
        os.remove(a.cmd_file)
    if i % 50 == 0:
        open(a.idx_file, "w").write(str(i))
    s.write((l + "\n").encode())
    last = time.time()
    while True:
        r = s.readline().decode(errors="replace").strip()
        if r:
            last = time.time()
            if re.search(r"error|stop|kill|halt", r, re.I) and "busy" not in r:
                log(f"line {i} [{l}] -> {r}"); abort(r)
            if r.startswith("ok"):
                break
            if not r.startswith("T:") and "busy" not in r:
                log(f"{i}/{len(lines)} {l[:40]} | {r[:80]}")
        elif time.time() - last > 900:
            abort(f"timeout on line {i}: {l}")
    if i % 500 == 0:
        log(f"progress {i}/{len(lines)}")
log("DONE")
