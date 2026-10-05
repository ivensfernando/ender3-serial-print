# How the serial control works

This document explains how a PC drives an Ender-3 V3 SE over USB: the path from a 3D model to a printed part, how the serial link works, how to pause and move the machine, what went wrong along the way, and whether a desktop program is worth writing. The short step-by-step procedure is in `README.md`.

## 1. The idea in one sentence

The printer is not controlled by magic software: its USB-C cable shows up on Linux as a **serial port** (`/dev/ttyUSB0`), and the Marlin firmware inside it understands **G-code as plain text**. Whoever sends one line of text and waits for the `ok` reply is operating the printer.

## 2. The path from model to part

- **Model**: OpenSCAD (or any CAD), exported to STL in print orientation.
- **Check**: `check_overhang.py` sums the surface that would hang in the air and need support.
- **Slice**: `slice_cura.py` turns the STL into G-code with CuraEngine 4.13, adding the start and end blocks for this printer.
- **Send**: `send_gcode.py` streams the G-code line by line over the serial port.
- **Run**: Marlin 1.0.6 heats, moves and extrudes.

In short: `model -> STL -> slice_cura.py -> G-code -> send_gcode.py -> serial port -> Marlin`.

## 3. The serial connection

- The USB-C port is a CH340 bridge (`1a86:7523`) at **115200 baud**. It is not a storage device: `M20`/`M21` answer "No SD card".
- Opening the port does not reset the board, so the axes stay homed.
- The user must be in the `dialout` group. In a fresh session, run commands through `sg dialout -c '...'`.
- The protocol is simple: send one line, the printer replies `ok` when it queues the command. While heating it sends `busy` or `T:...` lines to show it is alive.

### Commands that only read (they move nothing)

- `M115`: firmware version and machine type.
- `M105`: nozzle and bed temperature, and their targets.
- `M114`: current X Y Z E position.
- `M27`: "Not SD printing" when idle.
- `M119`: state of the end stops and the probe.
- `M401`, `M119`, `M402`, `M119`: probe test. Healthy: open with the pin deployed, triggered when stowed.
- `M420 V` and `M851`: the bed-leveling mesh and the Z offset (-1.36 on this machine).

## 4. Printing with `send_gcode.py`

A simple loop: read a line, write it, wait for `ok`. Built-in rules:

- **Stop**: create `/tmp/print.stop`. It turns the nozzle, bed and fan off and exits.
- **Any reply containing `error`, `kill` or `halt`** also turns everything off and exits.
- **Live commands**: write them to `/tmp/print.cmd`; they are sent between two lines of the part. This is how to change a temperature mid-print, or pause.
- **Progress**: `/tmp/print.log` shows `lines done / total`; `/tmp/print.idx` holds the current line.
- **Timeout**: 15 minutes with no reply at all aborts (the printer may just be heating, so it is long).

Standard command, in the background so the terminal is free:

```bash
sg dialout -c "nohup python3 send_gcode.py FILE.gcode >/tmp/print.out 2>&1 &"
tail /tmp/print.log
```

### Pause for one minute

Write this to `/tmp/print.cmd`. `G91` switches to relative mode, so the head position does not need to be known:

```
G91
G1 E-3 F1800     ; retract so the nozzle does not ooze
G1 Z20 F600      ; lift 20 mm
M400
G4 S60           ; wait 60 s
G1 Z-20 F600     ; lower again
G1 E3 F1800      ; give the filament back
G90              ; back to absolute mode
```

`G90` must come **after** lowering and un-retracting. If it comes first, the print continues 20 mm in the air.

### Moving the machine by hand (for example after lubricating it)

Send single moves, wait for `ok`, then send `M400` (it only answers when the move has finished). A safe sequence: lift the nozzle, `G28 X Y`, back-and-forth moves in X and in Y, diagonals, slow Z moves, then park and release the motors with `M84 X Y`. Re-home X and Y first if anyone may have touched the axes while the motors were off.

## 5. What went wrong, so it does not happen again

1. **Never open the port while a print runs.** Querying `M105` during a print made two readers collide, and `send_gcode.py` died with `multiple access on port` at 39%. To see progress, read `/tmp/print.log`.
2. **Full `G28` with a part on the plate.** The CR-Touch probe measures Z at the plate centre; with a part there the nozzle crashes. Use `G28 X Y` and resume without the probe.
3. **Motors off after a print.** The end block ends with `M84 X Y E`, so the head slides. Resuming needs `G28 X Y` and a lift first.
4. **`pkill -f send_gcode` kills your own shell** (the pattern is in its own command line). Use the PID, or the stop file.
5. **Counting processes with `grep` counts the command doing the counting.** Filter it out (`grep -v "bash -c"`).
6. **Full disk.** A runaway desktop log in `/tmp` grew to 81 GB because a VPN client repeated an IPC error. With a full disk the print log cannot be written and the sender dies. Check `df -h /` before a long print.
7. **Wrong material for fit tests.** ABS closes holes and sockets by about 1 mm, PLA much less. Test the fit in the same material as the final part.
8. **Time estimates.** The `;TIME:` line at the top of the G-code is wrong; the last `;TIME_ELAPSED:` is the real figure.

## 6. Limits of a host-side setup

- The host does not see the plate or hear the machine. It only knows what the printer answers over serial.
- It cannot remove a part, clean the plate or change filament. A human has to confirm "plate clean, filament loaded, room ventilated" before every print, otherwise the next part lands on top of the last one.
- Start, stop, pause and resume only when asked. Stopping a good print on your own initiative is a mistake.

## 7. Is a desktop program possible? Yes.

Nothing here is exclusive: it is a serial port, G-code and discipline. Two routes.

### A) Use an existing program (fastest)

- **OctoPrint** (a web server running on the same PC): upload, temperatures, controls, pause, history. It is the closest to what these scripts do and handles Marlin 1.0.6 well.
- **Pronterface / Printrun**, or **Cura** with USB printing: simpler, one window.

For everyday use, OctoPrint needs no code at all.

### B) Write your own (Python)

It is feasible. A design that works:

```
[ window / browser ] <--> [ Python server ] <--> [ ONE owner of the serial port ] <--> Marlin
   buttons, graphs          command queue          thread that writes and waits for "ok"
```

Main parts:

1. **A single owner of the serial port.** This is lesson number 1 above. Everything (G-code, `M105`, jogging) goes into one queue and is sent in order; never a second process.
2. **A queue that tracks `ok`.** Send a line, wait for `ok`, handle `busy`, `T:` and `error`.
3. **Temperature**: send `M105` through the same queue every 2 s and plot it.
4. **Controls**: jog (0.1 / 1 / 10 / 50 mm steps), home X Y, temperatures, fan, extrusion.
5. **Printing**: open a `.gcode`, show progress by lines (and time left from `;TIME_ELAPSED`), pause and resume as in section 4, and a stop button that switches the heaters off.
6. **Slicing inside the program**: call `slice_cura.py` and show the result.
7. **Checks before starting**: free disk, printer idle, temperatures, "plate clean? window open?".
8. **Logging**: one log per print, and clean up old ones.

Libraries: `pyserial` for the port, `FastAPI` or `Flask` for the server, a simple HTML page or `PySide6` for the window. A minimal version (connect, jog, temperature, print, stop) is a few days of work; pause/resume and an integrated slicer add more.

Limits to consider:

- Printing from the PC needs the PC awake for the whole print. For a 3-hour part that matters.
- Protection against thermal runaway lives in the printer firmware. The program does not replace it.
- Without a camera the program is as blind as the scripts. A USB camera with a live view would be the next useful step.
