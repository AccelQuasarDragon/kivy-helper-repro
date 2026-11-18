# Run: uv run --no-project --with pillow tests/test_devicelab_media.py
"""Regression guard for tools/devicelab_media.py (temp dirs only, a fake artifact; the video part needs
ffmpeg + ffprobe on PATH and is skipped with a SKIP line without them):
- PNGs: only whitelisted chunks survive (tEXt / iTXt / zTXt / eXIf / tIME / iCCP dropped), pixels kept,
  bytes after IEND dropped; a bad CRC / not a PNG / no IEND is refused;
- only Test Lab's screenshots (+ video) are copied: logcat, tombstones, ftl.log, sitemap.png never are;
- `images` list: a name not in the artifact is refused; "all" = every screenshot in number order;
- facts parsed from ftl.log / robo.json / file names; devicelab.json is what card_page.py accepts;
- video: re-muxed without metadata (a planted title tag is gone), frames + strip.png written;
- a symlink in the artifact is refused (skipped where symlinks cannot be made);
- --extract: the zip's sha256 must equal the cleared digest; members with absolute / .. / drive / backslash
  paths or symlink mode bits are refused; a good zip unpacks;
- Test Lab's "--" (no details) is not shown as details.
Exit 0 = all pass, 1 = a failure."""
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import hashlib
import zlib

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
TOOL = os.path.join(ROOT, 'tools', 'devicelab_media.py')
spec = importlib.util.spec_from_file_location('devicelab_media', TOOL)
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)
cspec = importlib.util.spec_from_file_location('card_page', os.path.join(ROOT, 'tools', 'card_page.py'))
cp = importlib.util.module_from_spec(cspec)
cspec.loader.exec_module(cp)
FAILS = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f' ({detail})' if detail and not cond else ''))
    if not cond:
        FAILS.append(name)


def chunk(typ: bytes, body: bytes) -> bytes:
    return struct.pack('>I', len(body)) + typ + body + struct.pack('>I', zlib.crc32(typ + body))


def png(w=4, h=4, extra=(), rgb=(200, 30, 30)) -> bytes:
    raw = b''.join(b'\x00' + bytes(rgb) * w for _ in range(h))
    body = [chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))]
    body += [chunk(t, b) for t, b in extra]
    body += [chunk(b'IDAT', zlib.compress(raw)), chunk(b'IEND', b'')]
    return dm.SIG + b''.join(body)


def chunk_types(data: bytes) -> list:
    out, i = [], 8
    while i < len(data):
        n = int.from_bytes(data[i:i + 4], 'big')
        out.append(data[i + 4:i + 8])
        i += 12 + n
    return out


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb' if isinstance(data, bytes) else 'w', **({} if isinstance(data, bytes) else {'encoding': 'utf-8'})) as f:
        f.write(data)


FTL_LOG = '''Robo testing complete.
┌─────────┬───────────────────────┬─────────────────────┐
│ OUTCOME │    TEST_AXIS_VALUE    │     TEST_DETAILS    │
├─────────┼───────────────────────┼─────────────────────┤
│ Failed  │ redfin-30-en-portrait │ Application crashed │
└─────────┴───────────────────────┴─────────────────────┘
19:08:03 Done. Test time = 128 (secs)
'''


def fake_artifact(root: str, video: bool) -> str:
    axis = os.path.join(root, 'results', 'redfin-30-en-portrait')
    meta = [(b'tEXt', b'Comment\x00secret-device-id'), (b'iTXt', b'XML:com.adobe.xmp\x00\x00\x00\x00\x00<x/>'),
            (b'tIME', b'\x07\xea\x0b\x12\x00\x00\x00'), (b'eXIf', b'MM\x00*'), (b'gAMA', struct.pack('>I', 45455))]
    for k in (0, 1, 2, 10):
        write(os.path.join(axis, 'artifacts', f'{k}.png'), png(extra=meta))
    write(os.path.join(axis, 'artifacts', 'output', 'sitemap.png'), png())
    write(os.path.join(axis, 'logcat'), 'secret logcat line\n')
    write(os.path.join(axis, 'SYSTEM_TOMBSTONE_1_x.txt'), 'tombstone\n')
    write(os.path.join(axis, 'data_app_native_crash_0_x.txt'), 'crash\n')
    write(os.path.join(root, 'ftl.log'), FTL_LOG)
    write(os.path.join(root, 'robo.json'), json.dumps([{'eventType': 'WAIT'}, {'eventType': 'POINT_TAP'}, {'eventType': 'POINT_TAP'}]))
    if video:
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=90x160:rate=10:duration=3',
                        '-f', 'lavfi', '-i', 'sine=duration=3', '-shortest', '-metadata', 'title=secret-title-xyz',
                        '-pix_fmt', 'yuv420p', os.path.join(axis, 'video.mp4')], check=True, capture_output=True)
    return axis


def main():
    # ---- strip_png ----
    meta_png = png(extra=[(b'tEXt', b'k\x00v'), (b'zTXt', b'k\x00\x00' + zlib.compress(b'v')), (b'iCCP', b'p\x00\x00' + zlib.compress(b'x')),
                          (b'sRGB', b'\x00')])
    out = dm.strip_png(meta_png + b'trailing junk')
    check('strip_png keeps IHDR/sRGB/IDAT/IEND only', chunk_types(out) == [b'IHDR', b'sRGB', b'IDAT', b'IEND'], chunk_types(out))
    check('strip_png drops bytes after IEND', out.endswith(chunk(b'IEND', b'')))
    try:
        from PIL import Image
        import io
        check('stripped PNG still decodes to the same pixels',
              Image.open(io.BytesIO(out)).convert('RGB').getpixel((1, 1)) == (200, 30, 30))
    except ImportError:
        print('SKIP pixel check (no Pillow: run with --with pillow)')
    bad = bytearray(meta_png)
    bad[40] ^= 0xFF
    for name, data in [('bad CRC', bytes(bad)), ('not a PNG', b'GIF89a' + b'\x00' * 40),
                       ('no IEND', meta_png[:-12]), ('first chunk not IHDR', dm.SIG + chunk(b'tEXt', b'a\x00b') + meta_png[8:])]:
        try:
            dm.strip_png(data)
            check(f'strip_png refuses: {name}', False, 'accepted')
        except ValueError:
            check(f'strip_png refuses: {name}', True)

    have_ff = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
    with tempfile.TemporaryDirectory() as tmp:
        art, out = os.path.join(tmp, 'art'), os.path.join(tmp, 'out')
        fake_artifact(os.path.join(art, '202'), have_ff)
        try:
            dm.one_run({'id': '202', 'images': ['0.png', '7.png'], 'video': False, 'frames': 0}, art, out)
            check('images list: a name not in the artifact is refused', False, 'accepted')
        except ValueError as exc:
            check('images list: a name not in the artifact is refused', '7.png' in str(exc))
        rec = dm.one_run({'id': '202', 'images': 'all', 'video': have_ff, 'frames': 3 if have_ff else 0}, art, out)
        d = os.path.join(out, '202')
        files = sorted(os.listdir(d))
        check('"all" = every screenshot, number order', rec['images'] == ['0.png', '1.png', '2.png', '10.png'], rec['images'])
        check('never copied: logcat, tombstones, crash txt, ftl.log, robo.json, sitemap.png',
              not any(x in files for x in ('logcat', 'SYSTEM_TOMBSTONE_1_x.txt', 'data_app_native_crash_0_x.txt',
                                           'ftl.log', 'robo.json', 'sitemap.png', 'output')), files)
        check('only png / mp4 / devicelab.json written',
              all(x.endswith('.png') or x in ('video.mp4', 'devicelab.json') for x in files), files)
        with open(os.path.join(d, '0.png'), 'rb') as f:
            types = chunk_types(f.read())
        check('published screenshot has no text / time / exif chunks', types == [b'IHDR', b'gAMA', b'IDAT', b'IEND'], types)
        check('no published file holds the planted secrets', not any(
            b'secret' in open(os.path.join(d, x), 'rb').read() for x in files))
        f = rec['facts']
        check('facts: device, outcome, details, test time, counts, taps',
              f.get('device') == 'redfin-30-en-portrait' and f.get('outcome') == 'Failed' and
              f.get('details') == 'Application crashed' and f.get('test_time_s') == 128 and
              f.get('screenshots') == 4 and f.get('crash_files') == 2 and f.get('taps') == 2, f)
        check('sheet.png written for the screenshots', rec['sheet'] == 'sheet.png' and 'sheet.png' in files)
        if have_ff:
            check('video re-muxed + 3 frames + strip.png', rec['video'] == 'video.mp4' and
                  rec['frames'] == ['frame_01.png', 'frame_02.png', 'frame_03.png'] and rec['strip'] == 'strip.png')
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format_tags:stream=codec_type', '-of', 'compact',
                                    os.path.join(d, 'video.mp4')], capture_output=True, text=True).stdout
            check('video: metadata title gone, audio stream dropped', 'secret' not in probe and 'audio' not in probe, probe)
            check('facts: video length', 2.5 <= f.get('video_s', 0) <= 3.5, f)
        else:
            print('SKIP video / frames (ffmpeg + ffprobe not on PATH)')
        # card_page.py accepts what devicelab_media.py wrote
        shots = os.path.join(tmp, 'shotsrc')
        shutil.copytree(out, os.path.join(shots, 'shots'))
        runs = [{'id': '202', 'images': None, 'label': 'phone'}]
        try:
            cp.load_folders(runs, shots)
            check('card_page.load_folders accepts devicelab.json', runs[0]['phone']['images'] == rec['images'])
        except ValueError as exc:
            check('card_page.load_folders accepts devicelab.json', False, str(exc))
        # symlink refusal
        link = os.path.join(art, '202', 'results', 'redfin-30-en-portrait', 'artifacts', '99.png')
        try:
            os.symlink(os.path.join(art, '202', 'ftl.log'), link)
        except (OSError, NotImplementedError):
            print('SKIP symlink refusal (cannot create symlinks here)')
        else:
            try:
                dm.one_run({'id': '202', 'images': 'all', 'video': False, 'frames': 0}, art, out)
                check('a symlink in the artifact is refused', False, 'accepted')
            except ValueError as exc:
                check('a symlink in the artifact is refused', 'symlink' in str(exc))
    # ---- --extract: digest pin + safe unzip ----
    with tempfile.TemporaryDirectory() as tmp:
        def mkzip(name, members):
            path = os.path.join(tmp, name)
            with zipfile.ZipFile(path, 'w') as z:
                for m, data, mode in members:
                    zi = zipfile.ZipInfo(m)
                    if mode:
                        zi.external_attr = mode << 16
                    z.writestr(zi, data)
            return path, 'sha256:' + hashlib.sha256(open(path, 'rb').read()).hexdigest()
        good, dg = mkzip('good.zip', [('ftl.log', 'x', 0), ('results/a-b/artifacts/0.png', 'p', 0o100644)])
        n = dm.extract(good, dg, os.path.join(tmp, 'g'))
        check('extract: digest match unpacks', n == 2 and os.path.isfile(os.path.join(tmp, 'g', 'results', 'a-b', 'artifacts', '0.png')))
        for label, args in [('digest mismatch', (good, 'sha256:' + '0' * 64)), ('digest malformed', (good, 'abc'))]:
            try:
                dm.extract(*args, os.path.join(tmp, 'x' + label[:3]))
                check(f'extract refuses: {label}', False, 'accepted')
            except ValueError:
                check(f'extract refuses: {label}', not os.path.exists(os.path.join(tmp, 'x' + label[:3])))
        for label, member in [('zip slip ..', ('../evil.txt', 'x', 0)), ('absolute path', ('/etc/x', 'x', 0)),
                              ('drive path', ('C' + ':/x', 'x', 0)), ('backslash path', ('a\\..\\x', 'x', 0)),
                              ('symlink entry', ('results/link', 'ftl.log', 0o120777))]:
            z, d = mkzip(label.replace(' ', '_') + '.zip', [member])
            try:
                dm.extract(z, d, os.path.join(tmp, 'o_' + label.replace(' ', '_')))
                check(f'extract refuses: {label}', False, 'accepted')
            except ValueError:
                check(f'extract refuses: {label}', not os.path.exists(os.path.join(tmp, 'o_' + label.replace(' ', '_'))))
        # "--" details
        axis = os.path.join(tmp, 'r', 'results', 'redfin-30-en-portrait')
        os.makedirs(axis)
        write(os.path.join(tmp, 'r', 'ftl.log'), FTL_LOG.replace('Failed ', 'Passed ').replace('Application crashed', '--                 '))
        f = dm.facts_of(os.path.join(tmp, 'r'), axis, 'redfin-30-en-portrait')
        check('facts: "--" details dropped, outcome kept', f.get('outcome') == 'Passed' and 'details' not in f, f)

    print(f'{len(FAILS)} failure(s)')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
