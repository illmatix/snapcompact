#!/usr/bin/env python3
"""SnapCompact PoC: render text into dense pixel-font PNGs for vision-model context compression.

Based on https://blog.can.ac/2026/06/10/snapcompact/ — ~40K chars fit in one
1568x1568 PNG that Anthropic bills as ~3.3K image tokens (vs ~10K text tokens).

Usage:
    snapcompact.py INPUT.txt [-o OUTDIR]

Writes INPUT.snap-001.png, INPUT.snap-002.png, ... and prints a token-cost summary.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANVAS = 1568                     # Anthropic max-res tile; billed (1568*1568)/750 ~= 3278 tokens
MARGIN = 8
# ponytail: PIL's built-in bitmap font is ~6x11 px, right in the article's 35-40 px^2/char sweet spot
FONT = ImageFont.load_default()
CHAR_W, CHAR_H = 6, 11
LINE_GAP = 0
# line color cycling — article: raised small-VL decode confidence 0.39 -> 0.94
COLORS = ["#000000", "#00358f", "#7a0000", "#004a00"]

COLS = (CANVAS - 2 * MARGIN) // CHAR_W          # 258 chars per row
ROWS = (CANVAS - 2 * MARGIN) // (CHAR_H + LINE_GAP)  # 141 rows per page

NEWLINE_GLYPH = "¶"  # pack text as one continuous stream; source newlines stay visible (latin-1, PIL default font has it)


def wrap_lines(text):
    stream = text.replace("\n", NEWLINE_GLYPH)
    return [stream[i:i + COLS] for i in range(0, len(stream), COLS)]


def render(lines):
    img = Image.new("RGB", (CANVAS, CANVAS), "white")
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
    for n, page in enumerate(pages, 1):
        path = outdir / f"{args.input.stem}.snap-{n:03d}.png"
        render(page).save(path)
        print(path)

    text_tokens = len(text) // 4
    image_tokens = len(pages) * (CANVAS * CANVAS) // 750
    print(f"\n{len(text):,} chars on {len(pages)} page(s): "
          f"~{text_tokens:,} text tokens -> ~{image_tokens:,} image tokens "
          f"({text_tokens / max(image_tokens, 1):.1f}x compression)", file=sys.stderr)


if __name__ == "__main__":
    main()
