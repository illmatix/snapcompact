#!/usr/bin/env python3
"""SnapCompact PoC: render text into dense pixel-font PNGs for vision-model context compression.

Based on https://blog.can.ac/2026/06/10/snapcompact/ — ~40K chars fit in one
1568x1568 PNG that Anthropic bills as ~3.3K image tokens (vs ~10K text tokens).

Usage:
    snapcompact.py INPUT.txt [-o OUTDIR]

Writes INPUT.snap-001.png, INPUT.snap-002.png, ... and prints a token-cost summary.
"""
import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANVAS = 1568                     # Anthropic max-res tile; billed (1568*1568)/750 ~= 3278 tokens
MARGIN = 8
# DejaVu Mono at 9 renders ~5.4x14 px — same density as PIL's 6x11 bitmap font, but
# antialiased glyphs keep 6/8 distinct (bitmap font measured 6<->8 flips in recall tests)
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",         # debian/ubuntu
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",  # fedora
    str(Path.home() / "Library/Fonts/DejaVuSansMono.ttf"),         # macOS: brew install --cask font-dejavu
    "/Library/Fonts/DejaVuSansMono.ttf",                           # macOS system-wide
]
try:
    FONT = ImageFont.truetype(next(p for p in _FONT_PATHS if Path(p).exists()), 9)
except StopIteration:
    sys.exit("snapcompact: DejaVu Sans Mono not found "
             "(apt install fonts-dejavu-core / brew install --cask font-dejavu)")
CHAR_W = FONT.getlength("M")  # monospace: every glyph has the same advance
CHAR_H = sum(FONT.getmetrics())
LINE_GAP = 0
# line color cycling — article: raised small-VL decode confidence 0.39 -> 0.94
COLORS = ["#000000", "#00358f", "#7a0000", "#004a00"]

COLS = int((CANVAS - 2 * MARGIN) // CHAR_W)          # 286 chars per row
ROWS = (CANVAS - 2 * MARGIN) // (CHAR_H + LINE_GAP)  # 129 rows per page

NEWLINE_GLYPH = "¶"  # pack text as one continuous stream; source newlines stay visible (latin-1, PIL default font has it)


# recall tests: remaining misreads cluster in long random hex (a few chars per 40).
# Flips are independent per char, so a second copy lets the reader cross-check.
HEX_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")


def wrap_lines(text):
    text = HEX_RE.sub(lambda m: f"{m.group(0)} [dup:{m.group(0)}]", text)
    stream = text.replace("\n", NEWLINE_GLYPH)
    return [stream[i:i + COLS] for i in range(0, len(stream), COLS)]


def render(lines):
    # crop to used rows — Anthropic bills (w*h)/750, so a short last page costs less
    h = MARGIN * 2 + max(len(lines), 1) * (CHAR_H + LINE_GAP)
    img = Image.new("RGB", (CANVAS, h), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        y = MARGIN + i * (CHAR_H + LINE_GAP)
        draw.text((MARGIN, y), line, font=FONT, fill=COLORS[i % len(COLORS)])
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--outdir", type=Path, default=None)
    args = ap.parse_args()

    text = args.input.read_text(errors="replace")
    outdir = args.outdir or args.input.parent
    outdir.mkdir(parents=True, exist_ok=True)

    lines = wrap_lines(text)
    pages = [lines[i:i + ROWS] for i in range(0, len(lines), ROWS)] or [[]]
    image_tokens = 0
    for n, page in enumerate(pages, 1):
        path = outdir / f"{args.input.stem}.snap-{n:03d}.png"
        img = render(page)
        image_tokens += img.width * img.height // 750
        img.save(path)
        print(path)

    text_tokens = len(text) // 4
    print(f"\n{len(text):,} chars on {len(pages)} page(s): "
          f"~{text_tokens:,} text tokens -> ~{image_tokens:,} image tokens "
          f"({text_tokens / max(image_tokens, 1):.1f}x compression)", file=sys.stderr)


if __name__ == "__main__":
    main()
