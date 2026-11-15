# /// script
# requires-python = '>=3.10'
# dependencies = []
# ///
"""List the Python packages bundled in an APK (stdlib only), as markdown.

Opens the APK (a zip) and every archive nested inside it (zip / tar / tar.gz,
e.g. p4a's private.tar or a python bundle), found by magic bytes, not by name.
Reports: libpython versions, `<name>-<ver>.dist-info` / `.egg-info` metadata,
and site-packages top-level names that ship no metadata (p4a recipes often don't).
Usage: apk_pkgs.py APP.apk   (uv run --script tools/apk_pkgs.py APP.apk)
"""
import io
import re
import sys
import tarfile
import zipfile

META = re.compile(r'(?:^|/)([A-Za-z0-9_.]+)-([^/-]+)\.(dist-info|egg-info)(?:/|$)')
SITE = re.compile(r'(?:^|/)site-packages/([^/]+)')
LIBPY = re.compile(r'libpython(3\.\d+)')
MAX_NESTED = 400 * 1024 * 1024


def kind(head: bytes) -> str | None:
    if head.startswith(b'PK\x03\x04'):
        return 'zip'
    if head.startswith(b'\x1f\x8b'):
        return 'tgz'
    if len(head) > 262 and head[257:262] == b'ustar':
        return 'tar'
    return None


def walk(data: bytes, where: str, found: dict, depth: int = 0) -> None:
    k = kind(data[:512])
    names: list[tuple[str, callable]] = []
    if k == 'zip':
        zf = zipfile.ZipFile(io.BytesIO(data))
        for info in zf.infolist():
            names.append((info.filename, (lambda i=info: zf.read(i)) if info.file_size < MAX_NESTED else None))
    elif k in {'tar', 'tgz'}:
        try:
            tf = tarfile.open(fileobj=io.BytesIO(data), mode='r:*')
            for m in tf.getmembers():
                getter = (lambda m=m: tf.extractfile(m).read()) if m.isfile() and m.size < MAX_NESTED else None
                names.append((m.name, getter))
        except tarfile.TarError:
            return
    else:
        return
    found['archives'].append(where or '(apk)')
    for name, getter in names:
        full = f'{where}!{name}' if where else name
        m = META.search(name)
        if m:
            found['meta'].add((m.group(1), m.group(2), m.group(3), full.split('!')[0]))
        s = SITE.search(name)
        if s:
            found['site'].add(re.sub(r'\.(py|pyc|so)$|\.cpython.*$', '', s.group(1)))
        lp = LIBPY.search(name)
        if lp and name.endswith('.so'):
            found['libpython'].add(f'{lp.group(1)} ({name})')
        if getter and depth < 3 and not name.endswith(('.png', '.jpg', '.ttf', '.otf', '.dex')):
            body = getter()
            if kind(body[:512]):
                walk(body, full, found, depth + 1)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], 'rb') as f:
        data = f.read()
    found = {'archives': [], 'meta': set(), 'site': set(), 'libpython': set()}
    walk(data, '', found)
    print(f'- python: {", ".join(sorted(found["libpython"])) or "no libpython*.so found"}')
    print(f'- archives scanned: {", ".join(found["archives"])}')
    print('\n| package | version | metadata | in |\n|---|---|---|---|')
    named = set()
    for name, ver, how, where in sorted(found['meta'], key=lambda t: t[0].lower()):
        named.add(name.lower().replace('-', '_'))
        print(f'| {name} | {ver} | {how} | {where} |')
    bare = sorted(n for n in found['site']
                  if n.lower().replace('-', '_') not in named and not META.search(n + '/') and n != '__pycache__')
    print(f'\nsite-packages names without metadata: {", ".join(bare) or "none"}')


if __name__ == '__main__':
    main()
