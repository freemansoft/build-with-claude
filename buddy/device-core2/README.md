# buddy / device-core2

Claude Buddy for the **M5Stack Core2** (ESP32, 320x240 touchscreen, three
touch buttons under the screen). Port of the Cardputer-Adv bundle in
[`../device/`](../device/).

## What's shared and what isn't

| File | Source |
|------|--------|
| `buddy_ble.py`, `buddy_protocol.py`, `buddy_state.py`, `buddy_chars.py`, `burst_frames.py` | symlinks to `../device/` — same BLE stack, wire protocol, NVS state and sprite frames |
| `buddy_ui_core2.py` | Core2 view (320x240, DejaVu18/24/56, vibration on new prompts) |
| `buddy_pet_core2.py` | plays the pet animation (see [Pet](#pet)) |
| `pet_frames.py` | the pet's frames — generated from `pet_art/`, don't edit by hand |
| `apps/claude_buddy.py` | Core2 app loop: touch buttons, real AXP192 battery readings |
| `main.py` | Core2 launcher (no WiFi, no keyboard) |

The Cardputer's `hello_cardputer.py` and `snake.py` aren't included —
they need the Cardputer keyboard.

## Install

The normal `m5-onboard` commands recognize a Core2 that is running
UIFlow 2.0 (via `scripts/identify.py`) and pick the Core2 firmware and
this bundle automatically:

```bash
python3 .claude/skills/m5-onboard/scripts/onboard.py --apps buddy        # flash + install
python3 .claude/skills/m5-onboard/scripts/onboard.py                     # UIFlow 2.0 firmware only
python3 .claude/skills/m5-onboard/scripts/install_apps.py --port /dev/cu.usbserial-XXXX --src buddy   # apps only
```

A blank Core2 (no MicroPython yet) can't be identified — name it:

```bash
python3 .claude/skills/m5-onboard/scripts/onboard.py --variant core2 --apps buddy-core2
```

Installing sets NVS `uiflow.boot_option=2`, so the Core2 boots into
`main.py` (this launcher) instead of UIFlow's own startup.

## Screen

Connected, top to bottom:

- **Header** — the link state on the right (`WAITING` / `PAIRING` /
  `LINKED` / `OFF`). On the left, while linked, the session counts from
  Desktop's heartbeat (`Run 1  Wait 0  Total 2`); otherwise "Claude
  Buddy" (or the name set from Claude Desktop).
- **Request area** (five rows) — an orange **Allow:** box you can answer
  with A/B, a yellow **Waiting for approval** box to answer in the app
  (both with a small alarmed [pet](#pet) on the left), or, with nothing
  to approve, the full-size pet with Desktop's latest status message
  beside it.
- **Bottom row** — `Today: 53.3k tokens` (the heartbeat's
  `tokens_today`: output tokens since local midnight) and the battery
  (`100% USB` on USB power, `87%` on battery).
- **Button labels** — Approve · Deny · Hold: exit.

Level and approve/deny counts are still kept on the device and reported
to Claude Desktop, but aren't shown on screen.

## Pet

When nothing is waiting for approval, an animated pixel pet — the
**blob**, a round Claude-orange critter with an antenna spark — sits in
the request area:

| State | When |
|-------|------|
| idle | linked, no session running: bobs, blinks, looks around |
| busy | one or more sessions running: focused, spark flashing, sweating |
| sleep | no session running for 60 s, or napping (below): eyes closed, Z's drifting up |
| dizzy | you shook the Core2: X eyes, wobbling, stars (~2 s) |
| heart | you touched the pet, or approved a request on the device within 5 s of it arriving: hearts float up (~2 s) |
| attention | a request box is up: a smaller (64 px) pet with wide eyes and a "!" hops beside the request text |

**Nap:** lay the Core2 face-down for about a second and the pet sleeps
with the backlight dimmed (see [Battery](#battery)); pick it up and it
wakes. A request arriving
ends the nap so the screen is bright when you turn it over.

When a request comes in, the approve/deny box takes the pet's place,
with the alarmed pet drawn at 2x on the box's left and the request text
(about 226 px wide) beside it; hearts earned by a quick approval play
once the box clears. Shake, nap and touch only work while the full-size
pet is showing.

The motion sensor and touch screen are only read while the pet is on
screen. Shake is the same test as the Hardware Buddy reference: total
acceleration jumping more than 0.8 g from its running average.
No timer runs longer than a few seconds, so nothing depends on
`ticks_ms` staying in range for days.

### Art pipeline

The art is 32x32 pixel PNGs, drawn on the Core2 at 3x (96x96):

```
pet_art/blob/
├── manifest.json   palette, frames per state, playback order, frame time
├── idle_0.png ...  one transparent PNG per frame
└── preview.png     every frame at 6x, for review
```

```bash
cd buddy
python3 scripts/draw_blob_pet.py    # (re)draw the blob's PNGs from code
python3 scripts/gen_pet_frames.py   # PNGs + manifest -> device-core2/pet_frames.py
```

Both need Pillow (`pip install pillow`). To redraw the pet by hand, edit
the PNGs in any pixel editor (Piskel, Aseprite, ...), keep them 32x32
with a transparent background and the manifest's palette, then run only
`gen_pet_frames.py` — `draw_blob_pet.py` would overwrite your PNGs.

`pet_frames.py` stores each frame as runs of
`(y, x, length, colour)` bytes (about 8.7 KB for all 21 frames). On the
device, `buddy_pet_core2.py` renders each frame once into an off-screen
canvas in PSRAM (18 KB each) and shows it with one `push` (about 3 ms),
so frames change all at once with no flicker.

## Battery

On battery (detected from the battery current, checked every 3 s), the
app saves power; plugged into USB, everything stays at UIFlow's
defaults:

- **5 V port output off** — the 5 V boost that feeds the M-Bus / Grove
  ports (`M5.Power.setExtOutput`). Nothing in this app uses them.
- **CPU at 80 MHz** instead of 240 MHz. BLE and the pet run fine.
- **Backlight follows activity:**

  | Level | When (on battery) |
  |-------|-------------------|
  | 127 (full) | a request, pairing or unpair screen is up, or for 30 s after a button press, touch, shake, or plugging in / unplugging |
  | 40 | idle |
  | 10 | the pet is asleep (no session running for 60 s) |

  Face-down nap dims to 10 on battery or USB.

### Measurements

Battery draw on a Core2 v1.0 linked to Claude Desktop, read from the
AXP192 (`M5.Power.getBatteryCurrent`, 10 s average), with each setting
added on top of the previous one:

| Setting | Draw | Saved |
|---------|-----:|------:|
| As it was (brightness 127, 5 V output on, 240 MHz) | 86 mA | — |
| Brightness 40 | 74 mA | 12 mA |
| + 5 V port output off | 59 mA | 15 mA |
| + CPU 80 MHz | 49 mA | 10 mA |
| + main loop every 100 ms instead of 40 ms | 48 mA | 1 mA — not adopted (slower buttons and touch) |
| Brightness 10 (instead of 40) | 44 mA | 4 mA |

So idle on battery goes from ~86 mA to ~49 mA (~44 mA with the pet
asleep): roughly 4.5 h to 8–9 h on the Core2's ~390 mAh battery.

## Buttons

| | BtnA (left) | BtnB (middle) | BtnC (right) |
|-|-------------|---------------|--------------|
| Launcher | up | open | down |
| Claude Buddy | approve once | deny | hold ~1 s to exit |
| Unpair request | confirm | cancel | — |

## Connecting

1. Open **Claude Buddy** from the launcher. The screen shows the device's
   BLE name (e.g. `Claude_44747E`).
2. In Claude Desktop: **Help → Troubleshooting → Enable Developer Tools**
   (one-time), then **Developer → Hardware Buddy → Connect** and pick that
   name.

## Approving requests

When Claude Desktop sends an answerable permission request, the Core2
buzzes and shows an orange **Allow:** box — press **A** to approve or
**B** to deny.

Claude Desktop doesn't always include the request. Testing with Claude
Code sessions in Claude Desktop: Bash requests with short commands
(up to ~35 characters, e.g. `say "my name is joe"`) arrived with a
`"prompt"` and were approved/denied from the device; longer ones
(~70+ characters) and question dialogs arrived as heartbeats with
`"waiting": 1` but no `"prompt"`. The device link uses the default
20-byte BLE payload (the app doesn't request a larger MTU), which may
be why Desktop leaves larger prompts out — untested. Without a request
id there is nothing to answer, so the device shows a yellow **Waiting
for approval** box and "Approve in the app". With one session
running it also shows the tool call (taken from Desktop's `evt`
stream); with several, it shows "N waiting for approval" and how many
sessions are running instead, since the latest tool call may belong to
a different session than the one waiting.

Heartbeats are combined across all sessions, so the device buzzes once
when the waiting count goes up or a prompt with a new id arrives — not
on tool calls, which other (auto-approved) sessions also send.

## Status reply

Claude Desktop polls `{"cmd":"status"}` every couple of seconds for the
Hardware Buddy window's stats panel. The Core2 app answers in the shape
the [Hardware Buddy reference](https://github.com/anthropics/claude-desktop-buddy/blob/main/REFERENCE.md)
specifies — `{"ack":"status","ok":true,"data":{name, sec, bat, sys, stats}}`
— with `bat.mA` negative while charging. Velocity isn't supported for
now: `stats.vel` is always 0 ("no data" in the reference), so Desktop
shows `--s`. It does this with a small `_Protocol` subclass in
`apps/claude_buddy.py`; the shared `buddy_protocol.py` (and so the
Cardputer bundle) still sends the older shape — see `../README.md` for
the gap and the planned fix.

`stats.deny` counts only denials pressed on the device (B); requests
denied in the Claude app never reach it. `stats.nap` (idle periods,
not seconds) and `stats.lvl` (from approvals, not tokens) differ from
the reference on purpose for now — they feed pet features, which
aren't built yet.

## Debugging what Desktop sends

Create an empty `/flash/buddy_rx.log` on the device (from the REPL:
`open('/flash/buddy_rx.log','w').close()`) and Claude Buddy appends
every line it receives (capped at 16 KB). Delete the file to stop —
the log contains tool-call text from your Claude session.

## Back to stock UIFlow

From the device REPL:

```python
import esp32; n = esp32.NVS('uiflow'); n.set_u8('boot_option', 1); n.commit()
import machine; machine.reset()
```
