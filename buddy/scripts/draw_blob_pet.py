"""Build-time: draw the Core2 Buddy's "blob" pet as 32x32 PNG frames.

The blob is an original character for this project: a round
Claude-orange critter with an antenna spark. Rather than hand-typing
every frame, each one is composed from a few parts (body, eyes, mouth,
antenna spark, extras like Z's or a "!") so the frames stay consistent
and a tweak to, say, the eyes carries through every state.

Output, under ``buddy/device-core2/pet_art/blob/``:

- one transparent 32x32 PNG per frame (``idle_0.png`` ...), which any
  pixel editor (Piskel, Aseprite, ...) can open and redraw;
- ``manifest.json``: palette, per-state frame lists, playback order and
  frame time;
- ``preview.png``: every frame at 6x on a black background, for review.

``gen_pet_frames.py`` turns the PNGs + manifest into the on-device
``pet_frames.py``. If you redraw a PNG by hand, skip this script and
just re-run ``gen_pet_frames.py`` (re-running this one overwrites the
PNGs).

Usage:
    python3 scripts/draw_blob_pet.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

_ROOT = Path(__file__).resolve().parent.parent
_OUT_DIR = _ROOT / "device-core2" / "pet_art" / "blob"

SIZE = 32

# Palette: one character per colour. "." is transparent.
PALETTE = {
    "E": 0x6E2F1E,  # outline
    "O": 0xD97757,  # body (Claude orange)
    "D": 0xB55A3C,  # body shade
    "H": 0xF2A68A,  # body highlight
    "K": 0x1A1110,  # eyes / mouth
    "W": 0xFFFFFF,  # eye glint, spark core
    "P": 0xF4A09A,  # cheeks
    "Y": 0xFFD27A,  # antenna spark
    "S": 0x7FC8F8,  # sweat drop
    "Z": 0xC9D6FF,  # sleep Z's
    "!": 0xFFE14D,  # attention mark
    "R": 0xFF5C7A,  # hearts
}


class Frame:
    def __init__(self):
        self.px = [["."] * SIZE for _ in range(SIZE)]

    def put(self, x, y, c):
        if 0 <= x < SIZE and 0 <= y < SIZE:
            self.px[y][x] = c

    def get(self, x, y):
        if 0 <= x < SIZE and 0 <= y < SIZE:
            return self.px[y][x]
        return "."

    def rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, c)

    def stamp(self, x, y, rows, c):
        """Draw a small glyph given as strings; '#' = colour c."""
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch == "#":
                    self.put(x + dx, y + dy, c)

    def shifted(self, dx):
        """Copy of this frame moved dx pixels sideways (for wobbles)."""
        g = Frame()
        for y in range(SIZE):
            for x in range(SIZE):
                g.put(x + dx, y, self.px[y][x])
        return g


# ---- parts -----------------------------------------------------------------


def body(f, top, bottom, left=4, right=27, r_top=8, r_bot=4):
    """Rounded blob: big radius on top, small at the bottom, with a
    dark outline, shading low and on the right, and a highlight."""
    inside = set()
    for y in range(top, bottom + 1):
        inset = 0.0
        if y < top + r_top:
            d = top + r_top - y - 0.5
            inset = r_top - math.sqrt(max(0.0, r_top * r_top - d * d))
        elif y > bottom - r_bot:
            d = y - (bottom - r_bot) - 0.5
            inset = r_bot - math.sqrt(max(0.0, r_bot * r_bot - d * d))
        x0 = left + int(round(inset))
        x1 = right - int(round(inset))
        for x in range(x0, x1 + 1):
            inside.add((x, y))
    for (x, y) in inside:
        edge = any((x + dx, y + dy) not in inside for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if edge:
            c = "E"
        elif y >= bottom - 2 or (x + 2, y) not in inside:
            c = "D"
        else:
            c = "O"
        f.put(x, y, c)
    # Highlight: a short arc near the top-left of the body.
    hx, hy = left + 5, top + 3
    for x, y in ((hx, hy + 1), (hx + 1, hy), (hx + 2, hy), (hx, hy + 2)):
        if (x, y) in inside:
            f.put(x, y, "H")
    return inside


def feet(f, y, cx=16):
    for x0 in (cx - 7, cx + 3):
        f.rect(x0, y, 4, 2, "E")
        f.rect(x0 + 1, y, 2, 1, "D")


def eye(f, x, y, kind):
    """x, y = top-left of a 2x3 eye cell."""
    if kind == "open":
        f.rect(x, y, 2, 3, "K")
        f.put(x, y, "W")
    elif kind in ("left", "right"):
        dx = -1 if kind == "left" else 1
        f.rect(x + dx, y, 2, 3, "K")
        f.put(x + dx, y, "W")
    elif kind == "down":
        f.rect(x, y + 1, 2, 3, "K")
        f.put(x, y + 1, "W")
    elif kind == "wide":
        f.rect(x - 1, y - 1, 3, 4, "K")
        f.put(x - 1, y - 1, "W")
        f.put(x, y - 1, "W")
    elif kind == "blink":
        f.rect(x - 1, y + 2, 4, 1, "K")
    elif kind == "sleep":  # closed, curved down
        f.stamp(x - 1, y + 1, ("#..#", ".##."), "K")
    elif kind == "happy":  # ^ ^
        f.stamp(x - 1, y + 1, (".##.", "#..#"), "K")
    elif kind == "x":  # dizzy
        f.stamp(x - 1, y, ("#..#", ".##.", "#..#"), "K")


def eyes(f, top, kind):
    y = top + 5
    eye(f, 11, y, kind)
    eye(f, 20, y, kind)
    return y


def cheeks(f, eye_y):
    f.rect(8, eye_y + 4, 2, 1, "P")
    f.rect(23, eye_y + 4, 2, 1, "P")


def mouth(f, eye_y, kind):
    y = eye_y + 5
    if kind == "smile":
        f.stamp(14, y, ("#..#", ".##."), "K")
    elif kind == "flat":
        f.rect(15, y + 1, 2, 1, "K")
    elif kind == "o":
        f.stamp(15, y, ("##", "##"), "K")
    elif kind == "small":
        f.put(16, y + 1, "K")
    elif kind == "focus":  # tongue-out concentration
        f.rect(14, y + 1, 4, 1, "K")
        f.put(16, y + 2, "P")
    elif kind == "wavy":
        f.stamp(13, y + 1, ("#.#.#.", ".#.#.#"), "K")
    elif kind == "grin":
        f.stamp(13, y, ("######", ".#PP#."), "K")
        f.rect(15, y + 1, 2, 1, "P")


def antenna(f, top, spark):
    """Stem rising from the top of the body, with a spark on the tip.
    spark: "big" | "small" | "off"."""
    cx = 16
    for y in range(top - 3, top):
        f.put(cx, y, "E")
    sy = top - 5
    if spark == "big":
        for d in (1, 2):
            for x, y in ((cx - d, sy), (cx + d, sy), (cx, sy - d), (cx, sy + d)):
                f.put(x, y, "Y")
        f.put(cx, sy, "W")
    elif spark == "small":
        for x, y in ((cx - 1, sy), (cx + 1, sy), (cx, sy - 1), (cx, sy + 1)):
            f.put(x, y, "Y")
        f.put(cx, sy, "W")
    else:
        f.put(cx, sy + 1, "D")


def zzz(f, x, y, big):
    if big:
        f.stamp(x, y, ("#####", "...#.", "..#..", ".#...", "#####"), "Z")
    else:
        f.stamp(x, y, ("###", "..#", ".#.", "#..", "###"), "Z")


def bang(f, x, y):
    f.rect(x, y, 2, 5, "!")
    f.rect(x, y + 6, 2, 2, "!")


def sweat(f, x, y):
    f.stamp(x, y, ("..#.", ".##.", "####", "####", ".##."), "S")


def star(f, x, y):
    f.stamp(x, y, (".#.", "###", ".#."), "Y")


def heart(f, x, y, big=True):
    if big:
        f.stamp(x, y, (".#.#.", "#####", "#####", ".###.", "..#.."), "R")
    else:
        f.stamp(x, y, ("#.#", "###", ".#."), "R")


# ---- frames ----------------------------------------------------------------


def make(top, eye_kind, mouth_kind, spark, cheek=True, bottom=None, feet_y=None, **extra):
    f = Frame()
    bottom = top + 15 if bottom is None else bottom
    feet(f, bottom + 1 if feet_y is None else feet_y)
    body(f, top, bottom)
    ey = eyes(f, top, eye_kind)
    if cheek:
        cheeks(f, ey)
    mouth(f, ey, mouth_kind)
    antenna(f, top, spark)
    for x, y, big in extra.get("z", ()):
        zzz(f, x, y, big)
    if "bang" in extra:
        bang(f, *extra["bang"])
    if "sweat" in extra:
        sweat(f, *extra["sweat"])
    for x, y in extra.get("stars", ()):
        star(f, x, y)
    for x, y, big in extra.get("hearts", ()):
        heart(f, x, y, big)
    dx = extra.get("dx", 0)
    return f.shifted(dx) if dx else f


def frames():
    """Return {state: (frame_ms, [frames], seq)}; seq indexes [frames]."""
    T = 12  # resting top of the body; bottom = 27, feet at 28-29
    idle = [
        make(T, "open", "smile", "small"),
        make(T + 1, "open", "smile", "small", bottom=27, feet_y=28),  # squash
        make(T, "blink", "smile", "small"),
        make(T, "left", "smile", "small"),
        make(T, "right", "smile", "small"),
    ]
    idle_seq = [0, 0, 1, 1, 0, 0, 1, 1, 0, 2, 0, 0, 1, 1, 0, 3, 3, 3, 0, 4, 4, 4, 0, 1, 1, 0, 2, 0]

    sleep = [
        make(T + 2, "sleep", "small", "off", bottom=27, feet_y=28, z=((22, 6, False),)),
        make(T + 1, "sleep", "small", "off", bottom=27, feet_y=28, z=((24, 3, False),)),
        make(T + 2, "sleep", "small", "off", bottom=27, feet_y=28, z=((26, 0, True),)),
    ]
    sleep_seq = [0, 1, 2, 1]

    busy = [
        make(T, "down", "focus", "big", sweat=(27, 6)),
        make(T - 1, "down", "focus", "small", bottom=27, feet_y=28, sweat=(27, 8)),
        make(T, "down", "focus", "big", sweat=(27, 10)),
        make(T - 1, "down", "focus", "small", bottom=27, feet_y=28),
    ]
    busy_seq = [0, 1, 2, 3]

    attention = [
        make(T - 2, "wide", "o", "big", bottom=25, feet_y=26, bang=(3, 2)),
        make(T, "wide", "o", "small", bang=(3, 2)),
    ]
    attention_seq = [0, 1]

    # Shaken: X eyes, wobbly mouth, swaying side to side, stars circling.
    dizzy = [
        make(T, "x", "wavy", "off", dx=-2, stars=((4, 6), (24, 3))),
        make(T, "x", "wavy", "off", dx=0, stars=((9, 2), (25, 8))),
        make(T, "x", "wavy", "off", dx=2, stars=((3, 3), (20, 7))),
        make(T, "x", "wavy", "off", dx=0, stars=((5, 9), (19, 2))),
    ]
    dizzy_seq = [0, 1, 2, 3]

    # Petted / quick approval: happy eyes, grin, hearts floating up.
    hearts = [
        make(T, "happy", "grin", "small", hearts=((24, 8, False),)),
        make(T - 1, "happy", "grin", "big", bottom=27, feet_y=28, hearts=((24, 4, True), (4, 8, False))),
        make(T, "happy", "grin", "small", hearts=((25, 0, True), (3, 4, True))),
    ]
    hearts_seq = [0, 1, 2]

    return {
        "idle": (220, idle, idle_seq),
        "sleep": (650, sleep, sleep_seq),
        "busy": (150, busy, busy_seq),
        "attention": (200, attention, attention_seq),
        "dizzy": (110, dizzy, dizzy_seq),
        "heart": (240, hearts, hearts_seq),
    }


def _to_image(f):
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    px = img.load()
    for y in range(SIZE):
        for x in range(SIZE):
            c = f.px[y][x]
            if c != ".":
                v = PALETTE[c]
                px[x, y] = ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF, 255)
    return img


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    states = {}
    all_imgs = []
    for state, (ms, fs, seq) in frames().items():
        names = []
        for i, f in enumerate(fs):
            name = "{}_{}.png".format(state, i)
            img = _to_image(f)
            img.save(_OUT_DIR / name)
            names.append(name)
            all_imgs.append((state, i, img))
        states[state] = {"frame_ms": ms, "frames": names, "seq": seq}

    manifest = {
        "name": "blob",
        "size": SIZE,
        "palette": ["#{:06X}".format(v) for v in PALETTE.values()],
        "states": states,
    }
    (_OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # Preview sheet: one row per state, frames at 6x on black.
    scale, pad = 6, 8
    cell = SIZE * scale
    rows = list(states)
    cols = max(len(s["frames"]) for s in states.values())
    sheet = Image.new("RGB", (pad + cols * (cell + pad), pad + len(rows) * (cell + pad)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for state, i, img in all_imgs:
        r = rows.index(state)
        x = pad + i * (cell + pad)
        y = pad + r * (cell + pad)
        sheet.paste(img.resize((cell, cell), Image.NEAREST), (x, y), img.resize((cell, cell), Image.NEAREST))
        draw.text((x + 4, y + 4), "{} {}".format(state, i), fill=(90, 90, 90))
    sheet.save(_OUT_DIR / "preview.png")
    print("wrote {} frames + manifest.json + preview.png to {}".format(len(all_imgs), _OUT_DIR))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
