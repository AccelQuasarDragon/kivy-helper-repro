# /// script
# requires-python = '>=3.10'
# dependencies = ['pillow>=10.1']
# ///
"""Phone media of devicelab.yml runs -> shots/<run_id>/ folders for a report (report.yml `media` job).
One generator: (a devicelab artifact, the run's cleared `media` spec) -> a folder laid out like an
inspect run's (PNG screenshots at the top level, sheet.png), so card_page.py's `images` / `embed` and
the contact sheet use phone screenshots and video frames exactly like emulator screenshots.

  devicelab_media.py --extract ZIP --digest sha256:<hex> --dest DIR
      (the artifact zip as the artifacts API serves it: refused unless its sha256 = the digest the operator
       cleared; then unzipped with every member checked: no absolute / .. paths, no symlinks, size caps)
  devicelab_media.py --plan PLAN.json --artifacts DIR --out DIR
  PLAN = card_page.py --run-ids --media-plan output: [{"id", "artifact", "digest", "images": "all" | [names],
         "video", "frames", "replace"}]
  DIR/<id>/ = that run's devicelab-<n>-a<k> artifact, unzipped (results/<device axis>/..., ftl.log, robo.json)
  OUT/<id>/ = <n>.png (the screenshots, Test Lab's own names), frame_01.png ... (sampled from the video),
              strip.png (the frames in one row), sheet.png (contact sheet of the screenshots),
              video.mp4 (re-muxed), devicelab.json (what is there + run facts; card_page.py reads it)

What is copied: ONLY top-level PNGs of results/<axis>/artifacts/ (Test Lab's screenshots) and
results/<axis>/video.mp4. Never logcat, tombstones or any other file (facts are counted / parsed, not copied).
Every PNG is rewritten with a chunk whitelist (no tEXt / iTXt / zTXt / eXIf / tIME / iCCP ...; CRCs
checked); the video is re-muxed by ffmpeg with metadata and every non-video stream dropped.
Caps: PNG <= 8 MB each, video <= 50 MB after the re-mux (over = skipped with a note, the report still runs).
Symlinks anywhere in an artifact = refused. Exit 0 = written, 1 = refused / failed (one line on stderr).
Facts (devicelab.json `facts`): device axis, Test Lab outcome + details and test time (from ftl.log,
already redacted + scanned by devicelab.yml), screenshot count, video length, crash report file count,
scripted tap count (robo.json). Performance metrics are NOT in the artifact (docs/devicelab.md).
Locally: uv run --script tools/devicelab_media.py ... (needs ffmpeg + ffprobe on PATH for video / frames).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SIG = b'\x89PNG\r\n\x1a\n'
KEEP = {b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'gAMA', b'cHRM', b'sRGB', b'sBIT'}
PNG_MAX, VIDEO_MAX, VIDEO_IN_MAX = 8_000_000, 50_000_000, 200_000_000
IMAGES_MAX, FRAMES_MAX = 40, 12
SHOT = re.compile(r'[0-9]{1,4}\.png')
AXIS = re.compile(r'[a-z0-9][a-z0-9_-]{0,60}')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.png')
RUN_ID = re.compile(r'[1-9][0-9]{0,19}')
FACT = re.compile(r"[A-Za-z0-9 ,.()_:'/-]{0,80}")
OUTCOME = re.compile(r'│\s*(Passed|Failed|Inconclusive|Skipped|Flaky)\s*│\s*([A-Za-z0-9_-]+)\s*│\s*([^│\n]*?)\s*│')
TEST_TIME = re.compile(r'Test time = ([0-9]{1,6}) \(secs\)')
CRASH_FILE = re.compile(r'(?i)(tombstone|native_crash|crash)')


def strip_png(data: bytes) -> bytes:
    """A PNG with only the whitelisted chunks (pixels + colour info), CRCs checked; bytes after IEND
    dropped. Not a PNG / a bad chunk = ValueError."""
    if not data.startswith(SIG):
        raise ValueError('not a PNG')
    out, i, first = [SIG], len(SIG), True
    while True:
        if i + 12 > len(data):
            raise ValueError('PNG ends without IEND')
        n = int.from_bytes(data[i:i + 4], 'big')
        typ, body = data[i + 4:i + 8], data[i + 8:i + 8 + n]
        if len(body) != n or i + 12 + n > len(data):
            raise ValueError('PNG chunk runs past the end')
        crc = data[i + 8 + n:i + 12 + n]
        if zlib.crc32(typ + body).to_bytes(4, 'big') != crc:
            raise ValueError(f'PNG chunk {typ!r}: bad CRC')
        if first and typ != b'IHDR':
            raise ValueError('PNG does not start with IHDR')
        first = False
        if typ in KEEP:
            out.append(data[i:i + 12 + n])
        i += 12 + n
        if typ == b'IEND':
            return b''.join(out)


def copy_png(src: str, dst: str) -> None:
    if os.path.getsize(src) > PNG_MAX:
        raise ValueError(f'{os.path.basename(src)} is over {PNG_MAX} bytes')
    with open(src, 'rb') as f:
        data = strip_png(f.read())
    with open(dst, 'wb') as f:
        f.write(data)


def natural(name: str) -> list:
    return [(0, int(t), '') if t.isdigit() else (1, 0, t) for t in re.split(r'(\d+)', name) if t]


def no_links(root: str) -> None:
    for d, dirs, files in os.walk(root):
        for x in dirs + files:
            if os.path.islink(os.path.join(d, x)):
                raise ValueError(f'symlink in the artifact: {x!r}')


def probe_seconds(path: str) -> float:
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def ffmpeg(*args) -> None:
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', *args], check=True, capture_output=True)


def sheet(out: str, paths: list, height: int, cols: int) -> None:
    """contact_sheet.py's compose (same look as every other sheet), PNG <= PNG_MAX, then stripped."""
    import io
    from PIL import Image
    import contact_sheet
    tiles = [([contact_sheet.stem(p)], None, Image.open(p).convert('RGB')) for p in paths]
    while True:
        buf = io.BytesIO()
        contact_sheet.compose(tiles, height, cols).save(buf, 'PNG', optimize=True)
        if buf.tell() <= PNG_MAX or height <= contact_sheet.MIN_H:
            break
        height = max(contact_sheet.MIN_H, int(height * 0.8))
    with open(out, 'wb') as f:
        f.write(strip_png(buf.getvalue()))


def facts_of(root: str, axis_dir: str, axis: str) -> dict:
    f = {'device': axis}
    log = os.path.join(root, 'ftl.log')
    if os.path.isfile(log):
        with open(log, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
        m = OUTCOME.search(text)
        if m and m[2] == axis:
            f['outcome'] = m[1]
            if FACT.fullmatch(m[3]) and re.search('[A-Za-z]', m[3]):  # Test Lab prints "--" for no details
                f['details'] = m[3]
        m = TEST_TIME.search(text)
        if m:
            f['test_time_s'] = int(m[1])
    art = os.path.join(axis_dir, 'artifacts')
    f['screenshots'] = len([x for x in os.listdir(art) if SHOT.fullmatch(x)]) if os.path.isdir(art) else 0
    f['crash_files'] = len([x for x in os.listdir(axis_dir) if CRASH_FILE.search(x) and
                            os.path.isfile(os.path.join(axis_dir, x))])
    robo = os.path.join(root, 'robo.json')
    if os.path.isfile(robo):
        try:
            with open(robo, encoding='utf-8') as fh:
                acts = json.load(fh)
            f['taps'] = sum(1 for a in acts if isinstance(a, dict) and a.get('eventType') == 'POINT_TAP')
        except (ValueError, TypeError):
            pass
    return f


def one_run(item: dict, art_root: str, out_root: str) -> dict:
    rid = str(item.get('id', ''))
    if not RUN_ID.fullmatch(rid):
        raise ValueError(f'bad run id {rid!r}')
    root = os.path.join(art_root, rid)
    if not os.path.isdir(root):
        raise ValueError(f'run {rid}: no artifact folder')
    no_links(root)
    res = os.path.join(root, 'results')
    axes = sorted(x for x in os.listdir(res) if AXIS.fullmatch(x) and os.path.isdir(os.path.join(res, x))) \
        if os.path.isdir(res) else []
    if not axes:
        raise ValueError(f'run {rid}: no results/<device axis>/ folder in the artifact')
    notes = [] if len(axes) == 1 else [f'{len(axes)} device folders; only {axes[0]} is shown']
    axis, axis_dir = axes[0], os.path.join(res, axes[0])
    out = os.path.join(out_root, rid)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    art = os.path.join(axis_dir, 'artifacts')
    have = sorted((x for x in os.listdir(art) if SHOT.fullmatch(x) and os.path.isfile(os.path.join(art, x))),
                  key=natural) if os.path.isdir(art) else []
    want = item.get('images', 'all')
    if want == 'all':
        if len(have) > IMAGES_MAX:
            notes.append(f'{len(have)} screenshots; the first {IMAGES_MAX} are published')
        names = have[:IMAGES_MAX]
    else:
        if not isinstance(want, list) or not all(isinstance(x, str) and NAME.fullmatch(x) for x in want):
            raise ValueError(f'run {rid}: images must be "all" or PNG names')
        missing = [x for x in want if x not in have]
        if missing:
            raise ValueError(f'run {rid}: not among the artifact screenshots: {", ".join(missing)}')
        names = list(dict.fromkeys(want))[:IMAGES_MAX]
    for x in names:
        copy_png(os.path.join(art, x), os.path.join(out, x))
    rec = {'workflow': 'devicelab.yml', 'run_id': rid, 'images': names, 'frames': [], 'video': None,
           'strip': None, 'sheet': None, 'facts': facts_of(root, axis_dir, axis), 'notes': notes}
    if names:
        sheet(os.path.join(out, 'sheet.png'), [os.path.join(out, x) for x in names], 480, min(6, len(names)))
        rec['sheet'] = 'sheet.png'
    vid = os.path.join(axis_dir, 'video.mp4')
    frames = int(item.get('frames') or 0)
    if not 0 <= frames <= FRAMES_MAX:
        raise ValueError(f'run {rid}: frames 0-{FRAMES_MAX}')
    if item.get('video') and not os.path.isfile(vid):
        notes.append('no video.mp4 in the artifact')
    elif item.get('video'):
        if os.path.getsize(vid) > VIDEO_IN_MAX:
            raise ValueError(f'run {rid}: video.mp4 over {VIDEO_IN_MAX} bytes')
        secs = probe_seconds(vid)
        rec['facts']['video_s'] = round(secs, 1)
        tmp = os.path.join(out, 'video.tmp.mp4')
        ffmpeg('-i', vid, '-map', '0:v:0', '-c', 'copy', '-map_metadata', '-1', '-map_chapters', '-1',
               '-fflags', '+bitexact', '-movflags', '+faststart', tmp)
        size = os.path.getsize(tmp)
        if size > VIDEO_MAX:
            os.remove(tmp)
            notes.append(f'video.mp4 not published: {size // 1_000_000} MB is over the {VIDEO_MAX // 1_000_000} MB cap')
        else:
            os.replace(tmp, os.path.join(out, 'video.mp4'))
            rec['video'] = 'video.mp4'
        for k in range(frames):  # evenly spaced, centred in each slice of the video
            name = f'frame_{k + 1:02d}.png'
            raw = os.path.join(out, 'frame.tmp.png')
            ffmpeg('-ss', f'{secs * (k + 0.5) / frames:.3f}', '-i', vid, '-frames:v', '1', '-an',
                   '-map_metadata', '-1', raw)
            copy_png(raw, os.path.join(out, name))
            os.remove(raw)
            rec['frames'].append(name)
        if rec['frames']:
            sheet(os.path.join(out, 'strip.png'), [os.path.join(out, x) for x in rec['frames']], 480, len(rec['frames']))
            rec['strip'] = 'strip.png'
    if not names and not rec['video'] and not rec['frames']:
        raise ValueError(f'run {rid}: nothing to publish (no screenshots and no video in the artifact)')
    with open(os.path.join(out, 'devicelab.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rec, f, indent=1)
    return rec


ZIP_MAX, ZIP_FILES, ZIP_TOTAL = 300_000_000, 2000, 1_000_000_000
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


def extract(zpath: str, digest: str, dest: str) -> int:
    """Check the zip's sha256 against the cleared digest, then unzip it into dest (must not exist yet).
    Every member: a relative path without '..' / drive / backslash, a regular file or dir (no symlink
    mode bits), total and per-file size capped. Returns the file count."""
    if not DIGEST.fullmatch(digest or ''):
        raise ValueError('digest must be sha256:<64 hex>')
    if os.path.getsize(zpath) > ZIP_MAX:
        raise ValueError(f'artifact zip over {ZIP_MAX} bytes')
    h = hashlib.sha256()
    with open(zpath, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    if 'sha256:' + h.hexdigest() != digest:
        raise ValueError('artifact digest mismatch: these are not the bytes that were cleared')
    if os.path.exists(dest):
        raise ValueError(f'{dest} exists already')
    with zipfile.ZipFile(zpath) as z:
        infos = z.infolist()
        if len(infos) > ZIP_FILES or sum(i.file_size for i in infos) > ZIP_TOTAL:
            raise ValueError('artifact zip has too many files or is too big unpacked')
        for i in infos:
            name = i.filename
            parts = name.rstrip('/').split('/')
            if not name or name.startswith('/') or '\\' in name or ':' in name or any(x in ('', '.', '..') for x in parts):
                raise ValueError(f'unsafe path in the artifact zip: {name!r}')
            mode = (i.external_attr >> 16) & 0o170000
            if mode not in (0, 0o100000, 0o040000):
                raise ValueError(f'not a regular file in the artifact zip: {name!r}')
        os.makedirs(dest)
        n = 0
        for i in infos:
            target = os.path.join(dest, *i.filename.rstrip('/').split('/'))
            if i.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(i) as src, open(target, 'xb') as out:
                shutil.copyfileobj(src, out)
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--plan')
    ap.add_argument('--artifacts')
    ap.add_argument('--out')
    ap.add_argument('--extract', metavar='ZIP')
    ap.add_argument('--digest')
    ap.add_argument('--dest')
    a = ap.parse_args()
    if a.extract:
        if not (a.digest and a.dest):
            ap.error('--extract needs --digest and --dest')
        try:
            print(f'{a.dest}: {extract(a.extract, a.digest, a.dest)} file(s), digest ok')
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            print(f'devicelab_media: {type(exc).__name__}: {exc}', file=sys.stderr)
            return 1
        return 0
    if not (a.plan and a.artifacts and a.out):
        ap.error('--plan, --artifacts and --out are required (or --extract)')
    try:
        with open(a.plan, encoding='utf-8') as f:
            plan = json.load(f)
        if not isinstance(plan, list):
            raise ValueError('plan must be a JSON list')
        for item in plan:
            rec = one_run(item, a.artifacts, a.out)
            print(f'shots/{rec["run_id"]}/: {len(rec["images"])} screenshot(s), {len(rec["frames"])} frame(s), '
                  f'video {"yes" if rec["video"] else "no"}' + ''.join(f'; note: {n}' for n in rec['notes']))
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError) as exc:
        print(f'devicelab_media: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
