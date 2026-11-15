# /// script
# requires-python = '>=3.10'
# dependencies = ['pillow>=10']
# ///
"""Compose PNG screenshots into ONE contact sheet (a row per `--cols` images), each labelled
with its file stem. Usage: contact_sheet.py OUT.png IN1.png [IN2.png ...] [--height 720] [--cols 4]
Locally / in CI: uv run --script tools/contact_sheet.py sheet.png shots/*.png
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('images', nargs='+')
    ap.add_argument('--height', type=int, default=720, help='height of each tile (px)')
    ap.add_argument('--cols', type=int, default=4)
    a = ap.parse_args()
    tiles = []
    for path in a.images:
        im = Image.open(path).convert('RGB')
        w = max(1, round(im.width * a.height / im.height))
        tiles.append((os.path.splitext(os.path.basename(path))[0], im.resize((w, a.height))))
    label_h, gap = 28, 8
    font = ImageFont.load_default(size=20) if hasattr(ImageFont, 'load_default') else None
    cols = min(a.cols, len(tiles))
    rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
    width = max(sum(t.width for _, t in row) + gap * (len(row) + 1) for row in rows)
    height = len(rows) * (a.height + label_h + gap) + gap
    sheet = Image.new('RGB', (width, height), (32, 32, 32))
    draw = ImageDraw.Draw(sheet)
    y = gap
    for row in rows:
        x = gap
        for name, tile in row:
            sheet.paste(tile, (x, y))
            draw.text((x + 4, y + a.height + 4), name, fill=(235, 235, 235), font=font)
            x += tile.width + gap
        y += a.height + label_h + gap
    sheet.save(a.out, optimize=True)
    print(f'{a.out}: {len(tiles)} tiles, {width}x{height}')


if __name__ == '__main__':
    main()
