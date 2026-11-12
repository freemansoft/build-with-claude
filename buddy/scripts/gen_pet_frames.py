"""Build-time: convert a pet's PNG frames into the Core2's ``pet_frames.py``.

Input is a pet art folder (default ``device-core2/pet_art/blob/``)
holding ``manifest.json`` and one small transparent PNG per frame — as
written by ``draw_blob_pet.py`` or redrawn by hand in a pixel editor.

Every opaque pixel is mapped to the nearest colour in the manifest's
palette (pixels with alpha < 128 are transparent), and each frame is
encoded as horizontal runs of ``(y, x, length, colour_index)`` — one
byte each, in source-pixel coordinates. The device scales up by
``SCALE`` when it pre-renders each frame into an off-screen canvas, so
the module stays small (a few KB) and needs no PNG decoder on device.

Output module (MicroPython-importable):

    NAME, SIZE, SCALE
    PALETTE  tuple of 0xRRGGBB
    FRAMES   tuple of bytes (run data, one per frame)
    STATES   {state: (frame_ms, (frame index, ...))}  playback order

Usage:
    python3 scripts/gen_pet_frames.py [--art device-core2/pet_art/blob]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ART = _ROOT / "device-core2" / "pet_art" / "blob"
_DEFAULT_DEST = _ROOT / "device-core2" / "pet_frames.py"
_ALPHA_MIN = 128


def _hex(c: str) -> int:
    return int(c.lstrip("#"), 16)


def _nearest(rgb, palette):
    r, g, b = rgb
    best, best_d = 0, None
    for i, v in enumerate(palette):
        d = (r - (v >> 16 & 255)) ** 2 + (g - (v >> 8 & 255)) ** 2 + (b - (v & 255)) ** 2
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def _encode(path: Path, size: int, palette) -> bytes:
    img = Image.open(path).convert("RGBA")
    if img.size != (size, size):
        raise SystemExit("{}: expected {}x{}, got {}x{}".format(path.name, size, size, *img.size))
    px = img.load()
    out = bytearray()
    for y in range(size):
        x = 0
        while x < size:
            r, g, b, a = px[x, y]
            if a < _ALPHA_MIN:
                x += 1
                continue
            c = _nearest((r, g, b), palette)
            start = x
            while x < size:
                r, g, b, a = px[x, y]
                if a < _ALPHA_MIN or _nearest((r, g, b), palette) != c:
                    break
                x += 1
            out += bytes((y, start, x - start, c))
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--art", type=Path, default=_DEFAULT_ART, help="pet art folder with manifest.json")
    ap.add_argument("--dest", type=Path, default=_DEFAULT_DEST)
    ap.add_argument("--scale", type=int, default=3, help="on-device pixel scale (32 px x 3 = 96 px)")
    args = ap.parse_args()

    manifest = json.loads((args.art / "manifest.json").read_text())
    size = int(manifest["size"])
    palette = [_hex(c) for c in manifest["palette"]]
    if len(palette) > 255:
        sys.stderr.write("palette too large (max 255 colours)\n")
        return 2

    frames, index = [], {}
    states = {}
    for state, spec in manifest["states"].items():
        local = []
        for name in spec["frames"]:
            if name not in index:
                index[name] = len(frames)
                frames.append(_encode(args.art / name, size, palette))
            local.append(index[name])
        seq = spec.get("seq") or list(range(len(local)))
        states[state] = (int(spec["frame_ms"]), tuple(local[i] for i in seq))

    total = sum(len(f) for f in frames)
    lines = [
        '"""Generated pet animation — do NOT edit by hand.',
        "",
        "Pet: {}  ({}x{} px, drawn at {}x)".format(manifest.get("name", "?"), size, size, args.scale),
        "Frames: {}  Run data: {} bytes".format(len(frames), total),
        "Source: {}".format(args.art.relative_to(_ROOT) if args.art.is_relative_to(_ROOT) else args.art),
        "Regenerate with `python3 scripts/gen_pet_frames.py`.",
        '"""',
        "",
        "NAME = {!r}".format(manifest.get("name", "pet")),
        "SIZE = {}".format(size),
        "SCALE = {}".format(args.scale),
        "PALETTE = ({},)".format(", ".join("0x{:06X}".format(v) for v in palette)),
        "FRAMES = (",
    ]
    lines += ["    {!r},".format(f) for f in frames]
    lines.append(")")
    lines.append("STATES = {")
    for state, (ms, seq) in states.items():
        lines.append("    {!r}: ({}, {!r}),".format(state, ms, seq))
    lines.append("}")
    lines.append("")
    args.dest.write_text("\n".join(lines))
    sys.stderr.write("wrote {} ({} frames, {} bytes of run data)\n".format(args.dest, len(frames), total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
