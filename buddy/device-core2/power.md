# Power: USB vs. battery

How Claude Buddy on the Core2 manages power draw, and what it does
differently on USB and on battery. The code is `_battery` / `_set_power`
in [`apps/claude_buddy.py`](apps/claude_buddy.py) and `_tick_brightness`
in [`buddy_ui_core2.py`](buddy_ui_core2.py).

In short: on USB everything stays at UIFlow's defaults. On battery the
app turns off the 5 V port output, slows the CPU and dims the backlight
when nothing is happening.

## Detecting USB vs. battery

The app reads the battery current from the AXP192 power chip
(`M5.Power.getBatteryCurrent`) and counts the Core2 as **on battery**
when the battery is discharging by more than 20 mA
(`_ON_BATTERY_MA = -20`). Anything above that counts as **on USB**.

Measured on hardware:

| Situation            |                     Battery current |
| -------------------- | ----------------------------------: |
| On USB, charging     |                       about +100 mA |
| On USB, battery full |                                0 mA |
| On battery           | about −75 mA (the board's own draw) |

The −20 mA cutoff sits well clear of both the "full" and "on battery"
readings.

**Why not the USB voltage (VBUS)?** It would be the obvious check, but
it doesn't work here: while UIFlow's 5 V bus output is on, the AXP192
reads about 5 V on VBUS even when running on battery.

**When it's checked:**

- once when Claude Buddy starts, and
- every 3 s after that, along with the footer refresh.

The power settings change only when the result changes, so switching
between USB and battery takes effect within about 3 s.

## What changes on battery

| Setting                                                         | On USB                                              | On battery                               |
| --------------------------------------------------------------- | --------------------------------------------------- | ---------------------------------------- |
| 5 V output to the M-Bus / Grove ports (`M5.Power.setExtOutput`) | on                                                  | off (nothing in this app uses the ports) |
| CPU speed (`machine.freq`)                                      | 240 MHz                                             | 80 MHz (BLE and the pet run fine)        |
| Backlight                                                       | full (127)                                          | follows activity (below)                 |
| LED bars (AWS IoT EduKit edition, GPIO25)                       | flash once every 5 s while a request is outstanding | off                                      |

### Backlight

On battery:

| Level      | When                                                                                                                                                                   |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 127 (full) | a request (either **Allow:** or **Waiting for approval**), pairing or unpair screen is up, or for 30 s after a button press, touch, shake, or plugging in / unplugging |
| 40         | idle                                                                                                                                                                   |
| 10         | the pet is asleep (no session running for 60 s)                                                                                                                        |

Laying the Core2 face-down (a [nap](README.md#pet)) dims to 10 on
battery **or** USB. Claude Buddy also starts at full brightness for the
first 30 s after launch.

The backlight level is picked in one place (`_tick_brightness`) on
every pass of the main loop. It's sent to the screen only when the
level changes.

### LED bars

The Core2 for AWS IoT EduKit has two side bars of five SK6812 LEDs in
its battery base. On USB they flash amber for 200 ms every 5 s while a
permission request is outstanding (an **Allow:** or **Waiting for
approval** box). They stop as soon as the request closes: answered on
the device, answered or cancelled in the app, or the link drops. On
battery they stay off. They're turned off when switching to battery
and before the exit reset (the LEDs keep their colour across a reset
while they have power).

The app can't tell an AWS edition from a plain Core2 (or detect any
battery base), so it assumes the bars are there whenever it's on USB.
On a plain Core2 that means GPIO25 on the M-Bus gets LED data while a
request is open on USB. Not measured: the bars only light on USB, so
they don't affect battery draw.

## What the device reports

- **Footer:** the battery shows as `100% USB` on USB and as a plain
  percentage (`87%`) on battery.
- **Status reply to Claude Desktop:** `bat` is `{pct, mV, mA, usb}`.
  `mA` follows the
  [Hardware Buddy reference](https://github.com/anthropics/claude-desktop-buddy/blob/main/REFERENCE.md)
  convention and is **negative while charging**, the opposite sign of
  the AXP192 reading. `usb` is the same on-USB test as above.

If a battery read fails, the app treats the device as on USB. That
leaves everything at UIFlow's defaults rather than dimming the screen
by mistake.

## Leaving the app

Exiting Claude Buddy (hold C) resets the Core2 (`machine.reset()`), so
the CPU speed, 5 V output and backlight all go back to UIFlow's
defaults. No separate restore step is needed.

## Measurements

Battery draw on a Core2 v1.0 linked to Claude Desktop, read from the
AXP192 (`M5.Power.getBatteryCurrent`, 10 s average), with each setting
added on top of the previous one:

| Setting                                            |  Draw |                                         Saved |
| -------------------------------------------------- | ----: | --------------------------------------------: |
| As it was (brightness 127, 5 V output on, 240 MHz) | 86 mA |                                             — |
| Brightness 40                                      | 74 mA |                                         12 mA |
| + 5 V port output off                              | 59 mA |                                         15 mA |
| + CPU 80 MHz                                       | 49 mA |                                         10 mA |
| + main loop every 100 ms instead of 40 ms          | 48 mA | 1 mA — not adopted (slower buttons and touch) |
| Brightness 10 (instead of 40)                      | 44 mA |                                          4 mA |

So idle on battery goes from ~86 mA to ~49 mA (~44 mA with the pet
asleep). That's roughly 4.5 h to 8–9 h on the Core2's ~390 mAh battery.
