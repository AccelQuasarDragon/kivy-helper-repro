# /// script
# requires-python = '>=3.10'
# dependencies = ['pillow>=10.1']
# ///
"""Compose PNG screenshots into ONE contact sheet. One generator, two inputs:
- plain:  contact_sheet.py OUT.png IN1.png [IN2.png ...] [--height 720] [--cols 4]
          (one run; each tile labelled with its file stem; inspect.yml's shots job)
- groups: contact_sheet.py OUT.png --groups manifest.json [--height 480] [--cols 0] [--max-bytes 8000000]
          manifest = [{"label": "run label", "images": ["path.png", ...]}, ...] (card_page.py --sheet-manifest
          writes it for report.yml): tiles flow across rows, each with a colour band per group and two lines
          (group label, file stem); --cols 0 = pick the column count for a roughly 16:9 sheet.
--font-size N: caption font px (default 20; 36 for the report highlights sheet embed.png).
--max-bytes > 0: if the PNG is bigger, re-render with tiles 20 % smaller (down to 160 px) until it fits,
else exit 1. Locally / in CI: uv run --script tools/contact_sheet.py ...
"""
import argparse
import io
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

BG, FG = (32, 32, 32), (235, 235, 235)
BANDS = [(66, 153, 225), (237, 137, 54), (72, 187, 120), (229, 62, 62), (159, 122, 234),
         (236, 201, 75), (56, 178, 172), (237, 100, 166)]
GAP, BAND_H, MIN_H = 8, 6, 160
FONT = 20  # caption font px (--font-size); a caption line is FONT + 6 px high


def stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def fit(draw, text: str, font, width: int) -> str:
    """text cut with an ellipsis to fit `width` px."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + '…', font=font) > width:
        text = text[:-1]
    return text + '…'


def compose(tiles, height: int, cols: int, font_size: int = FONT) -> Image.Image:
    """tiles = [(lines, band_colour_or_None, PIL image)] -> sheet image."""
    font = ImageFont.load_default(size=font_size)
    line_h = font_size + 6
    scaled = []
    for lines, band, im in tiles:
        w = max(1, round(im.width * height / im.height))
        scaled.append((lines, band, im.resize((w, height))))
    nlines = max(len(t[0]) for t in scaled)
    bands = any(t[1] for t in scaled)
    if cols <= 0:  # auto: about 16:9 overall
        avg_w = sum(t[2].width for t in scaled) / len(scaled)
        cell_h = height + nlines * line_h + (BAND_H if bands else 0)
        cols = max(1, round(math.sqrt(len(scaled) * 16 * cell_h / (9 * (avg_w + GAP)))))
    cols = min(cols, len(scaled))
    rows = [scaled[i:i + cols] for i in range(0, len(scaled), cols)]
    cell_h = (BAND_H if bands else 0) + height + nlines * line_h + GAP
    width = max(sum(t[2].width for t in row) + GAP * (len(row) + 1) for row in rows)
    sheet = Image.new('RGB', (width, len(rows) * cell_h + GAP), BG)
    draw = ImageDraw.Draw(sheet)
    y = GAP
    for row in rows:
        x = GAP
        for lines, band, tile in row:
            ty = y
            if bands:
                if band:
                    draw.rectangle([x, y, x + tile.width - 1, y + BAND_H - 1], fill=band)
                ty += BAND_H
            sheet.paste(tile, (x, ty))
            for k, line in enumerate(lines):
                draw.text((x + 4, ty + height + 3 + k * line_h), fit(draw, line, font, tile.width - 8),
                          fill=band if (band and k == 0 and len(lines) > 1) else FG, font=font)
            x += tile.width + GAP
        y += cell_h
    return sheet


def load_groups(path: str):
    with open(path, encoding='utf-8') as f:
        groups = json.load(f)
    if not isinstance(groups, list):
        raise ValueError('manifest must be a JSON list of {label, images}')
    tiles = []
    for g, group in enumerate(groups):
        band = BANDS[g % len(BANDS)]
        for img in group['images']:
            tiles.append(([str(group['label']), stem(img)], band, img))
    return tiles


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('images', nargs='*')
    ap.add_argument('--groups', help='JSON manifest [{label, images: [paths]}] (several runs on one sheet)')
    ap.add_argument('--height', type=int, help='tile height in px (default 720 plain, 480 groups)')
    ap.add_argument('--cols', type=int, help='tiles per row (default 4 plain, 0 = auto for groups)')
    ap.add_argument('--max-bytes', type=int, default=0, help='shrink tiles until the PNG fits (0 = no cap)')
    ap.add_argument('--font-size', type=int, default=FONT, help='caption font px (bigger for a highlights sheet, e.g. 36)')
    a = ap.parse_args()
    if a.groups:
        if a.images:
            ap.error('give images OR --groups, not both')
        tiles = load_groups(a.groups)
        height, cols = a.height or 480, 0 if a.cols is None else a.cols
    else:
        if not a.images:
            ap.error('no images')
        tiles = [([stem(p)], None, p) for p in a.images]
        height, cols = a.height or 720, 4 if a.cols is None else a.cols
    if not tiles:
        print('contact_sheet: no images', file=sys.stderr)
        return 1
    tiles = [(lines, band, Image.open(p).convert('RGB')) for lines, band, p in tiles]
    while True:
        sheet = compose(tiles, height, cols, a.font_size)
        buf = io.BytesIO()
        sheet.save(buf, 'PNG', optimize=True)
        if not a.max_bytes or buf.tell() <= a.max_bytes:
            break
        if height <= MIN_H:
            print(f'contact_sheet: {buf.tell()} bytes > {a.max_bytes} even at {height} px tiles', file=sys.stderr)
            return 1
        height = max(MIN_H, int(height * 0.8))
    with open(a.out, 'wb') as f:
        f.write(buf.getvalue())
    print(f'{a.out}: {len(tiles)} tiles, {sheet.width}x{sheet.height}, {buf.tell()} bytes, tile height {height}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
