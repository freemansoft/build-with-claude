"""Render the buddy's state to the 320x240 M5Stack Core2 LCD.

Same public API as ``buddy_ui_cp.BuddyUI`` (the Cardputer-Adv view), so
the shared protocol layer (``buddy_protocol``) and the app loop don't
care which display is underneath. Differences from the Cardputer view:

- 320x240 panel, so body text uses DejaVu18 (21 px line height measured
  on hardware) instead of DejaVu9.
- Input is the Core2's three touch buttons (BtnA / BtnB / BtnC), which
  sit in the touch strip *below* the LCD. The hint strip at the bottom
  of the screen labels each one directly above its touch zone.
- The Core2 has a vibration motor; a short buzz announces a newly
  pending permission prompt so you notice it without staring at the
  screen. ``tick()`` must be called from the main loop to stop it.

Layout (all y values are top-left of the glyph cell; drawString uses
TL_DATUM by default on UIFlow 2.0):

    y=0..29    header: connection badge on the right; on the left the
               session counts ("Run 1  Wait 0  Total 2") while linked,
               otherwise the title ("Claude Buddy" or a custom name)
    y=30       orange hairline
    y=31..201  main panel (idle / connected / passkey / unpair views)
               connected: request area y=38..167, five rows
               (with nothing to approve, it holds the 96x96 pet on the
               left and Desktop's status message on the right)
    y=176      footer: today's tokens + battery (connected view only)
    y=202      orange hairline
    y=203..239 hint strip: three labels centred over BtnA / BtnB / BtnC
"""

import math
import time

import M5

import buddy_pet_core2

# Anthropic palette — same values as buddy_ui_cp.py.
ORANGE = 0xCC785C
CREAM = 0xF0EEE6
DARK = 0x1F1F1F
BLACK = 0x000000
WHITE = 0xFFFFFF
GRAY_DIM = 0x333333
GRAY_MID = 0x777777
GREEN = 0x00FF00
CYAN = 0x00FFFF
YELLOW = 0xFFFF00
RED = 0xFF0000

_LCD = M5.Lcd

_W = 320
_H = 240

_HEADER_H = 30
_MAIN_Y = 31
_STRIP_Y = 203
_MAIN_H = _STRIP_Y - 1 - _MAIN_Y  # stop above the strip hairline
_FOOTER_Y = 176
_LINE_H = 22  # DejaVu18 cell is 21 px tall on hardware; +1 for descenders
_BOX_Y = 38   # request box / pet area, just under the header
_BOX_H = 130  # five 24 px rows + padding, ending above the footer at y=176
_BOX_ROWS = 5

# Horizontal centres of the three Core2 touch buttons (BtnA/B/C zones
# are each a third of the 320 px width).
_BTN_X = (53, 160, 267)

_VIBRATE_LEVEL = 200
_VIBRATE_MS = 300

# Pet: left side of the request area; status message to its right.
_PET_X = 8
_PET_Y = _BOX_Y + (_BOX_H - 96) // 2  # 96 px pet, centred vertically
_PET_TEXT_X = 114
# In the request boxes: a 2x (64 px) alarmed pet, centred vertically
# inside the box border, with the request text to its right.
_ALERT_X = 10
_ALERT_Y = _BOX_Y + (_BOX_H - 64) // 2
_ALERT_TEXT_X = _ALERT_X + 64 + 8
# With no session running for this long, the pet falls asleep.
_PET_SLEEP_MS = 60 * 1000
# One-shot animations (dizzy, hearts) play for this long.
_PET_ONCE_MS = 2200
# Approving on the device within this long of the request arriving
# earns hearts.
_QUICK_APPROVE_MS = 5000
# Shake: change in total acceleration (g) from its running average, as
# in the Hardware Buddy reference firmware.
_SHAKE_G = 0.8
# Face-down: z below this (g). Standing on the desk z is about +0.1,
# lying screen-up about +1.
_FACE_DOWN_Z = -0.7
# Face-down counter (sampled every other loop, ~80 ms): nap after 15
# samples down (~1.2 s), wake after 8 samples not down (~0.6 s). The
# hysteresis keeps sensor noise from flickering the backlight.
_NAP_ENTER = 15
_NAP_EXIT = -8

# Backlight levels (UIFlow's default is 127). Battery draw measured on a
# Core2 v1.0 (see apps/claude_buddy.py): 127 -> 40 saves ~12 mA, 40 ->
# 10 another ~4 mA.
_BRIGHT_FULL = 127
_BRIGHT_IDLE = 40     # on battery, nothing happening
_BRIGHT_ASLEEP = 10   # on battery, pet asleep
_BRIGHT_NAP = 10      # face-down, battery or USB
# On battery, full brightness for this long after a button press,
# touch, shake or plugging in / unplugging.
_ACTIVE_MS = 30 * 1000


def _font(name):
    """Select a DejaVu font by attribute name, tolerating builds that
    lack it (falls back to whatever font is current)."""
    try:
        _LCD.setFont(getattr(_LCD.FONTS, name))
    except Exception as e:
        print("buddy_ui_core2: setFont", name, "fallback:", e)
    _LCD.setTextSize(1)


def _clip(text, max_w):
    while text and _LCD.textWidth(text) > max_w:
        text = text[:-1]
    return text


def _wrap(text, max_w, n):
    """Split ``text`` into exactly ``n`` lines that each fit ``max_w`` px
    in the current font; overflow past the last line is dropped."""
    lines = []
    rest = " ".join((text or "").split())
    for _ in range(n):
        line = _clip(rest, max_w)
        # Prefer breaking at a space if one is reasonably close.
        if len(line) < len(rest):
            cut = line.rfind(" ")
            if cut > len(line) // 2:
                line = line[:cut]
        lines.append(line)
        rest = rest[len(line):].lstrip()
    return lines


def _tok_short(n):
    """Compact token count: 9,999 / 53.3k / 999.9k / 12.3M."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n < 10000:
        return "{:,}".format(n)
    if n < 1000000:
        return "{:.1f}k".format(n / 1000)
    return "{:.1f}M".format(n / 1000000)


def _right(pad, text):
    return _W - pad - _LCD.textWidth(text)


def _center(text, cx=_W // 2):
    return cx - _LCD.textWidth(text) // 2


class BuddyUI:
    """320x240 view for the Core2."""

    def __init__(self):
        self._last = {}
        self._passkey = None
        self._unpair_prompt = False
        self._connection_state = "advertising"
        self._prompt = None
        self._identity_name = "Buddy"
        self._identity_owner = ""
        self._device_name = ""
        self._footer = None  # last (stats, battery), repainted with main
        # What each incrementally-drawn row last showed (see _line).
        # Reset by _draw_main whenever the panel is fully repainted.
        self._drawn = {}
        self._buzz_until = 0
        # Latest tool call seen in Desktop's raw "evt" stream, as
        # (tool_name, summary). Shown when Desktop reports something
        # waiting for approval but doesn't send an answerable "prompt"
        # (observed for longer commands, ~70+ chars, and question dialogs).
        self._last_tool = None
        self._buzzed_prompt_id = None
        self._header_left = None  # last header-left (text, colour, right)
        self._pet = buddy_pet_core2.Pet(_PET_X, _PET_Y, BLACK)
        self._alert_pet = buddy_pet_core2.Pet(_ALERT_X, _ALERT_Y, BLACK, scale=2)
        self._alert_pet.set_state("attention")
        self._pet_quiet_since = None  # ticks_ms when sessions went idle
        self._pet_asleep = False
        # Sensors (read only while the pet is on screen).
        self._accel_base = 1.0
        self._imu_skip = False
        self._down = 0            # face-down counter, see _NAP_ENTER/_EXIT
        self._napping = False
        # Backlight (see _tick_brightness). Starts "active" so the
        # screen is full brightness for a while after launch.
        self._on_battery = False
        self._active = True
        self._active_since = time.ticks_ms()
        self._brightness = None
        self._touching = False
        # Quick-approve hearts: set when a new prompt arrives, cleared
        # once _QUICK_APPROVE_MS has passed (so no long timers).
        self._prompt_since = 0
        self._prompt_quick = False
        _LCD.fillScreen(BLACK)
        self._redraw_chrome()

    # ---- public setters (shape matches buddy_ui_cp.BuddyUI)

    def set_device_name(self, name: str):
        """Advertised BLE name, shown on the idle screen so you can
        pick the right device in Claude's Hardware Buddy list."""
        self._device_name = name or ""
        if self.is_idle():
            self._draw_main()

    def set_connection(self, state: str):
        if state == self._connection_state:
            return
        self._connection_state = state
        self._draw_header()
        if state in ("advertising", "disconnected"):
            self._prompt = None
            self._last = {}
        self._draw_main()
        self.restore_button_hints()

    def show_passkey(self, pk: int):
        self._passkey = pk
        self._draw_passkey_overlay()
        self.restore_button_hints()

    def clear_passkey(self):
        if self._passkey is None:
            return
        self._passkey = None
        self._draw_main()

    def show_unpair_prompt(self):
        self._unpair_prompt = True
        self._draw_unpair_overlay()
        self.restore_button_hints()
        self._buzz()

    def clear_unpair_prompt(self):
        if not self._unpair_prompt:
            return
        self._unpair_prompt = False
        self._draw_main()
        self.restore_button_hints()

    def update_heartbeat(self, hb: dict):
        prev_pending = bool(self._prompt)
        prev_waiting = self._count("waiting")
        self._last = hb
        self._prompt = hb.get("prompt")
        if self._showing_connected():
            self._draw_connected_main()  # incremental: no flicker
        else:
            self._draw_main()
        if bool(self._prompt) != prev_pending:
            self.restore_button_hints()
        # Buzz once per new request. Heartbeats are combined across all
        # sessions, so key off things that only change when something
        # new needs you: a prompt id we haven't seen, or the waiting
        # count going up. (Tool calls from other, auto-approved
        # sessions must not buzz.)
        pid = self._prompt.get("id") if self._prompt else None
        if pid is not None and pid != self._buzzed_prompt_id:
            self._buzzed_prompt_id = pid
            self._buzz()
            self._prompt_since = time.ticks_ms()
            self._prompt_quick = True
        elif pid is None and self._count("waiting") > prev_waiting:
            self._buzz()

    def _count(self, key) -> int:
        try:
            return int(self._last.get(key, 0) or 0)
        except (TypeError, ValueError, AttributeError):
            return 0

    def waiting_in_app(self) -> bool:
        """Desktop says something is waiting for approval, but sent no
        prompt we could answer — it has to be approved in the app."""
        return self._count("waiting") > 0 and not self._prompt

    def note_tool(self, name: str, summary: str, tool_id=None):
        """Record the latest tool call. State only, no drawing — safe to
        call from the BLE callback, so the "waiting" heartbeat that
        follows a few ms later already sees the right tool. ``tool_id``
        is accepted for the caller's convenience but not used."""
        self._last_tool = (name or "?", summary or "")

    def refresh_waiting(self):
        """Main-loop follow-up to note_tool(): repaint the waiting box
        with the new tool (no buzz — see update_heartbeat)."""
        if self.waiting_in_app() and self._showing_connected():
            self._draw_connected_main()

    def _showing_connected(self) -> bool:
        """True when the connected view (not idle, not an overlay) is
        what's on screen."""
        return (
            self._connection_state not in ("advertising", "disconnected")
            and self._passkey is None
            and not self._unpair_prompt
        )

    def update_identity(self, name: str, owner: str):
        # No separate identity row on the Core2: a custom name replaces
        # the "Claude Buddy" title in the header (shown while not
        # linked; linked, the header shows the session counts). The
        # default name ("Buddy") and the owner aren't shown.
        self._identity_name = name or "Buddy"
        self._identity_owner = owner or ""
        self._draw_header()

    def update_footer(self, stats: dict, battery: dict):
        self._footer = (stats, battery)
        if self._showing_connected():
            self._draw_footer(stats, battery)

    def flash_decision(self, decision: str):
        if decision == "once" and self._prompt_quick:
            # Hearts once the request box clears and the pet is back.
            self._pet.play_once("heart", _PET_ONCE_MS)
        self._prompt_quick = False
        color = GREEN if decision == "once" else RED
        label = "APPROVED" if decision == "once" else "DENIED"
        self.flash_toast(label, color)

    def flash_toast(self, text: str, color: int = CYAN):
        """Overwrite the hint strip with a one-line coloured status."""
        _font("DejaVu18")
        _LCD.fillRect(0, _STRIP_Y, _W, _H - _STRIP_Y, color)
        _LCD.setTextColor(WHITE, color)
        t = _clip(text, _W - 16)
        _LCD.drawString(t, _center(t), _STRIP_Y + 8)

    def restore_button_hints(self):
        """Label each touch button. Modes:
          - unpair confirmation: A confirm / B cancel
          - passkey on screen:   only C (hold to exit)
          - otherwise:           A approve / B deny / C hold-to-exit
        """
        _LCD.fillRect(0, _STRIP_Y - 1, _W, 1, ORANGE)
        _LCD.fillRect(0, _STRIP_Y, _W, _H - _STRIP_Y, DARK)
        _font("DejaVu18")
        if self._unpair_prompt:
            labels = (("Confirm", RED), ("Cancel", CREAM), ("", CREAM))
        elif self._passkey is not None:
            labels = (("", CREAM), ("", CREAM), ("Hold: exit", GRAY_MID))
        else:
            # Approve/Deny are brighter while a prompt is pending so it
            # is obvious they will do something right now.
            live = bool(self._prompt)
            labels = (
                ("Approve", GREEN if live else CREAM),
                ("Deny", RED if live else CREAM),
                ("Hold: exit", GRAY_MID),
            )
        for (text, color), cx in zip(labels, _BTN_X):
            if text:
                _LCD.setTextColor(color, DARK)
                _LCD.drawString(text, _center(text, cx), _STRIP_Y + 8)

    def is_idle(self) -> bool:
        return (
            self._connection_state in ("advertising", "disconnected")
            and self._passkey is None
            and self._prompt is None
            and not self._unpair_prompt
        )

    def tick(self):
        """Main-loop housekeeping: stop the vibration motor once its
        pulse has elapsed. Kept out of the BLE callback path so we never
        sleep inside a scheduled callback."""
        if self._buzz_until and time.ticks_diff(time.ticks_ms(), self._buzz_until) >= 0:
            self._buzz_until = 0
            try:
                M5.Power.setVibration(0)
            except Exception:
                pass
        if self._prompt_quick and (
            not self._prompt
            or time.ticks_diff(time.ticks_ms(), self._prompt_since) >= _QUICK_APPROVE_MS
        ):
            self._prompt_quick = False
        self._tick_pet()
        self._tick_brightness()

    def _tick_pet(self):
        """Pick the pet's state from the latest heartbeat and sensors, and
        advance its animation. Only draws while the pet's area is on
        screen. The small alarmed pet in a request box just animates."""
        if self._showing_connected() and self._drawn.get("box") in ("prompt", "waiting"):
            self._alert_pet.tick()
        if not (self._showing_connected() and self._drawn.get("box") == "pet"):
            # A request (or another view) took over: you'll want to
            # read it, so end any face-down nap.
            if self._napping:
                self._end_nap()
            self._down = 0
            self._touching = False
            return
        self._read_sensors()
        if self._napping:
            state = "sleep"
        elif self._count("running") > 0:
            state = "busy"
            self._pet_quiet_since = None
            self._pet_asleep = False
        else:
            now = time.ticks_ms()
            if self._pet_quiet_since is None:
                self._pet_quiet_since = now
            # Only measured until it falls asleep (60 s), so ticks_ms
            # wraparound (~6 days) never comes into it.
            if not self._pet_asleep and time.ticks_diff(now, self._pet_quiet_since) >= _PET_SLEEP_MS:
                self._pet_asleep = True
            state = "sleep" if self._pet_asleep else "idle"
        self._pet.set_state(state)
        self._pet.tick()

    def _read_sensors(self):
        """Shake -> dizzy, face-down -> nap (dimmed screen), touching
        the pet -> hearts."""
        # The IMU read takes ~3 ms over I2C, so sample every other loop.
        self._imu_skip = not self._imu_skip
        if not self._imu_skip:
            try:
                ax, ay, az = M5.Imu.getAccel()
            except Exception:
                az = None
            if az is not None:
                mag = math.sqrt(ax * ax + ay * ay + az * az)
                shake = abs(mag - self._accel_base) > _SHAKE_G
                self._accel_base = self._accel_base * 0.95 + mag * 0.05
                if shake and not self._napping and self._pet.state() != "dizzy":
                    self._pet.play_once("dizzy", _PET_ONCE_MS)
                    self.note_activity()
                if az < _FACE_DOWN_Z:
                    self._down = min(20, self._down + 1)
                else:
                    self._down = max(-10, self._down - 1)
                if not self._napping and self._down >= _NAP_ENTER:
                    self._start_nap()
                elif self._napping and self._down <= _NAP_EXIT:
                    self._end_nap()
        try:
            touching = M5.Touch.getCount() > 0
            if touching and not self._touching:
                self.note_activity()
                x, y = M5.Touch.getX(), M5.Touch.getY()
                p = self._pet
                if p.x <= x < p.x + p.size and p.y <= y < p.y + p.size:
                    self._pet.play_once("heart", _PET_ONCE_MS)
            self._touching = touching
        except Exception:
            pass

    def _start_nap(self):
        self._napping = True  # _tick_brightness dims the screen

    def _end_nap(self):
        self._napping = False
        self._pet_asleep = False
        self._pet_quiet_since = None  # idle again for a minute before sleeping
        self.note_activity()

    # ---- backlight

    def set_on_battery(self, on_battery: bool):
        """Battery brightness rules on/off (the app decides from the
        battery current). A change counts as activity, so plugging in
        or out lights the screen up."""
        self._on_battery = bool(on_battery)
        self.note_activity()

    def note_activity(self):
        """Something you did (button, touch, shake): full brightness for
        _ACTIVE_MS."""
        self._active = True
        self._active_since = time.ticks_ms()

    def _tick_brightness(self):
        """Pick the backlight level; only touches the LCD on a change.
        Face-down nap: dim. On USB: full. On battery: full while a
        request, pairing or unpair screen is up or for a while after
        activity, low while idle, lower while the pet sleeps."""
        if self._active and time.ticks_diff(time.ticks_ms(), self._active_since) >= _ACTIVE_MS:
            # Checked every loop, so this never waits long enough for
            # ticks_ms wraparound to matter.
            self._active = False
        if self._napping:
            level = _BRIGHT_NAP
        elif (
            not self._on_battery
            or self._active
            or self._prompt
            or self.waiting_in_app()
            or self._passkey is not None
            or self._unpair_prompt
        ):
            level = _BRIGHT_FULL
        elif self._pet_asleep:
            level = _BRIGHT_ASLEEP
        else:
            level = _BRIGHT_IDLE
        if level != self._brightness:
            try:
                _LCD.setBrightness(level)
                self._brightness = level
            except Exception as e:
                print("buddy_ui_core2: brightness:", e)

    def tick_idle_burst(self, frame, last_tick):
        return frame, last_tick

    # ---- helpers

    def _buzz(self):
        try:
            M5.Power.setVibration(_VIBRATE_LEVEL)
            self._buzz_until = time.ticks_add(time.ticks_ms(), _VIBRATE_MS)
        except Exception as e:
            print("buddy_ui_core2: vibration unavailable:", e)

    # ---- drawing

    def _draw_header(self):
        _LCD.fillRect(0, 0, _W, _HEADER_H, DARK)
        _LCD.fillRect(0, _HEADER_H, _W, 1, ORANGE)
        _font("DejaVu18")
        icon, color = self._connection_icon()
        _LCD.setTextColor(color, DARK)
        _LCD.drawString(icon, _right(8, icon), 5)
        self._header_left = None
        self._draw_header_left()

    def _draw_header_left(self):
        """Left side of the header. Linked: the session counts from
        Desktop's heartbeat (the pet says "Claude Buddy" well enough, and
        this frees a row in the main panel). Otherwise: the title — the
        custom name from Desktop, or "Claude Buddy". Called on every
        heartbeat, so it only repaints when the text changes."""
        _font("DejaVu18")
        icon, _ = self._connection_icon()
        right = _right(8, icon) - 10
        if self._connection_state == "encrypted":
            text = "Run {}  Wait {}  Total {}".format(
                self._count("running"), self._count("waiting"), self._count("total")
            )
            color = WHITE
        else:
            name = self._identity_name
            text = name if name and name != "Buddy" else "Claude Buddy"
            color = ORANGE
        sig = (text, color, right)
        if self._header_left == sig:
            return
        self._header_left = sig
        text = _clip(text, right - 8)
        _LCD.setTextColor(color, DARK)
        _LCD.drawString(text, 8, 5)
        end = 8 + _LCD.textWidth(text)
        if end < right:
            _LCD.fillRect(end, 4, right - end, _LINE_H, DARK)

    def _connection_icon(self):
        s = self._connection_state
        if s == "encrypted":
            return ("LINKED", GREEN)
        if s == "connected":
            return ("PAIRING", YELLOW)
        if s == "disconnected":
            return ("OFF", RED)
        return ("WAITING", CYAN)

    def _draw_main(self):
        # Full repaint: used for view changes (connect/disconnect,
        # overlays), not for routine heartbeats.
        self._drawn = {}
        self._pet.hide()
        self._alert_pet.hide()
        _LCD.fillRect(0, _MAIN_Y, _W, _MAIN_H, BLACK)
        if self._unpair_prompt:
            self._draw_unpair_overlay()
            return
        if self._passkey is not None:
            self._draw_passkey_overlay()
            return
        if self._connection_state in ("advertising", "disconnected"):
            self._draw_idle_main()
            return
        self._draw_connected_main()

    def _draw_idle_main(self):
        _font("DejaVu18")
        _LCD.setTextColor(CREAM, BLACK)
        _LCD.drawString("Waiting to connect...", 8, 44)
        _LCD.setTextColor(GRAY_MID, BLACK)
        _LCD.drawString("In Claude Desktop, open", 8, 78)
        _LCD.drawString("Developer > Hardware Buddy", 8, 102)
        _LCD.drawString("> Connect, and pick:", 8, 126)
        if self._device_name:
            _font("DejaVu24")
            _LCD.setTextColor(ORANGE, BLACK)
            dn = _clip(self._device_name, _W - 16)
            _LCD.drawString(dn, _center(dn), 160)

    def _line(self, key, text, x, y, fg, right=_W - 6):
        """Draw one DejaVu18 row without flicker: skip it entirely if
        it's unchanged since the last draw, otherwise paint the glyphs
        over the old ones (text background = BLACK) and blank only the
        leftover tail to the right. Never blanks the row first."""
        text = text or ""
        sig = (text, fg, x, right)
        if self._drawn.get(key) == sig:
            return
        self._drawn[key] = sig
        _font("DejaVu18")
        text = _clip(text, right - x)
        end = x
        if text:
            _LCD.setTextColor(fg, BLACK)
            _LCD.drawString(text, x, y)
            end = x + _LCD.textWidth(text)
        if end < right:
            _LCD.fillRect(end, y, right - end, _LINE_H, BLACK)

    def _draw_connected_main(self):
        """Connected view, drawn incrementally — called on every
        heartbeat, so it must not blank anything that hasn't changed."""
        hb = self._last
        self._draw_header_left()  # session counts live in the header
        _font("DejaVu18")  # _wrap/_clip below measure in this font

        # Request area (y=38..167, five rows): an orange prompt box
        # (answerable here), a yellow waiting box (approve in the app),
        # or the pet and the status message. Only a change of *kind*
        # clears it. Request boxes: the alarmed 64 px pet on the left,
        # text beside it.
        alert = self._alert_pet.available()
        box_x = _ALERT_TEXT_X if alert else 12
        box_w = _W - 12 - box_x
        if self._prompt:
            p = self._prompt
            hint = _wrap(str(p.get("hint", "")), box_w, _BOX_ROWS - 1)
            kind, border = "prompt", ORANGE
            rows = (("Allow: " + str(p.get("tool", "?")), ORANGE),) + tuple(
                (line, CREAM) for line in hint
            )
        elif self.waiting_in_app():
            kind, border = "waiting", YELLOW
            waiting = self._count("waiting")
            running = self._count("running")
            if running <= 1 and waiting == 1:
                # One session (a session waiting on you still counts as
                # running), so the latest tool call is the one waiting.
                tool = ""
                if self._last_tool:
                    name, summary = self._last_tool
                    tool = name + (": " + summary if summary else "")
                middle = tuple((line, CREAM) for line in _wrap(tool, box_w, _BOX_ROWS - 2))
                title = "Waiting for approval"
            else:
                # Several sessions: the latest tool call may belong to a
                # different session than the one waiting, so don't guess.
                middle = (("{} sessions running".format(running), CREAM),) + (
                    ("", CREAM),
                ) * (_BOX_ROWS - 3)
                title = "{} waiting for approval".format(waiting)
            where = "Approve in the app" if alert else "Approve in the Claude app"
            rows = ((title, YELLOW),) + middle + ((where, GRAY_MID),)
        elif self._pet.available():
            # Nothing to approve: the pet on the left, Desktop's status
            # message wrapped beside it.
            kind, border = "pet", None
            msg = _wrap(str(hb.get("msg", "") or ""), _W - 6 - _PET_TEXT_X, _BOX_ROWS)
            rows = tuple((line, GRAY_MID) for line in msg)
        else:
            kind, border = "msg", None
            rows = ((hb.get("msg", ""), GRAY_MID),) + (("", GRAY_MID),) * (_BOX_ROWS - 1)

        if self._drawn.get("box") != kind:
            if kind != "pet":
                self._pet.hide()
            if kind not in ("prompt", "waiting"):
                self._alert_pet.hide()
            _LCD.fillRect(0, _BOX_Y, _W, _BOX_H, BLACK)
            if border is not None:
                _LCD.drawRect(4, _BOX_Y, _W - 8, _BOX_H, border)
            self._drawn["box"] = kind
            for i in range(_BOX_ROWS):
                self._drawn.pop("row%d" % i, None)
            if kind == "pet":
                self._pet.show()
            elif kind in ("prompt", "waiting"):
                self._alert_pet.show()
        if kind == "pet":
            x, right = _PET_TEXT_X, _W - 6
        elif kind in ("prompt", "waiting"):
            x, right = box_x, _W - 12
        else:
            x, right = (8, _W - 6)
        for i, (text, color) in enumerate(rows):
            self._line("row%d" % i, text, x, _BOX_Y + 5 + 24 * i, color, right)

        if self._footer is not None:
            self._draw_footer(*self._footer)

    def _draw_unpair_overlay(self):
        if not self._unpair_prompt:
            return
        _LCD.fillRect(0, _MAIN_Y, _W, _MAIN_H, BLACK)
        _font("DejaVu24")
        _LCD.setTextColor(RED, BLACK)
        _LCD.drawString("UNPAIR REQUEST", 8, 44)
        _font("DejaVu18")
        _LCD.setTextColor(CREAM, BLACK)
        _LCD.drawString("From the connected computer.", 8, 86)
        _LCD.drawString("Wipes name, owner and stats,", 8, 112)
        _LCD.drawString("then disconnects.", 8, 136)

    def _draw_passkey_overlay(self):
        if self._passkey is None:
            return
        _LCD.fillRect(0, _MAIN_Y, _W, _MAIN_H, BLACK)
        _font("DejaVu18")
        _LCD.setTextColor(ORANGE, BLACK)
        _LCD.drawString("Pairing passkey:", 8, 44)
        pk_str = "{:06d}".format(self._passkey)
        _font("DejaVu56")
        _LCD.setTextColor(CREAM, BLACK)
        _LCD.drawString(pk_str, _center(pk_str), 80)
        _font("DejaVu18")
        _LCD.setTextColor(GRAY_MID, BLACK)
        _LCD.drawString("Type it into Claude", 8, 150)

    def _draw_footer(self, stats: dict, battery: dict):
        """Bottom row: today's tokens on the left, battery on the right.
        Called on every heartbeat and every 3 s; only repaints what
        changed. (Level/approve/deny stats are still kept in NVS and
        reported to Desktop — they're just not on screen.)"""
        y = _FOOTER_Y + 2
        _font("DejaVu18")
        pct = max(0, min(100, battery.get("pct", 0)))
        label = "{}%{}".format(pct, " USB" if battery.get("usb") else "")
        label_x = _right(8, label)
        if self._drawn.get("foot_r") != label:
            # Blank from just left of the label to the right margin,
            # which also covers a longer previous label ("100% USB").
            self._drawn["foot_r"] = label
            _LCD.fillRect(label_x - 10, y, _W - 6 - (label_x - 10), _LINE_H, BLACK)
            _LCD.setTextColor(CREAM, BLACK)
            _LCD.drawString(label, label_x, y)
        # Today's output tokens ("tokens_today": since local midnight,
        # per the Hardware Buddy reference), compact form (8,397 /
        # 53.3k / 15.0M) so it always fits beside the battery label.
        # The heartbeat's other count, "tokens", is cumulative since
        # Claude Desktop started — not shown.
        text = "Today: {} tokens".format(_tok_short(self._last.get("tokens_today", 0)))
        self._line("foot_l", text, 8, y, CYAN, right=label_x - 10)

    def _redraw_chrome(self):
        _LCD.fillScreen(BLACK)
        self._draw_header()
        self._draw_main()
        self.restore_button_hints()
