# /// script
# requires-python = '>=3.10'
# dependencies = []
# ///
"""Set key = value lines in a buildozer.spec (stdlib only).

Usage: patch_spec.py SPEC 'key=value' ['k1=v1;k2=v2' ...] ['key+=item']

A key that exists (commented or not) is replaced in place, so it stays in its
section; a key that does not exist is appended to [app]. Empty args are skipped.
'key+=a, b' appends each comma-separated item the key's current (uncommented)
value does not already list, e.g. 'android.archs+=x86_64'.
Locally: uv run tools/patch_spec.py work/buildozer.spec 'p4a.branch=develop'
"""
import re
import sys


def parse(args: list[str]) -> list[tuple[str, str]]:
    pairs = []
    for arg in args:
        for item in arg.split(';'):
            item = item.strip()
            if not item:
                continue
            if '=' not in item:
                sys.exit(f'bad override (no =): {item!r}')
            key, value = item.split('=', 1)
            pairs.append((key.strip(), value.strip()))  # 'k+' = append mode
    return pairs


# continuation lines of a multi-line value (configparser): indented, non-blank, right after the key line.
# An indented comment (# or ;) counts only when a real continuation line follows it: a trailing indented
# comment after a value is left in place, not swallowed.
CONT = r'(?:(?:\n[ \t]+[#;][^\n]*)*\n[ \t]+[^\s#;][^\n]*)*'


def patch(text: str, key: str, value: str) -> str:
    """Replace the uncommented `key =` line if there is one, else the first commented one. An
    uncommented one loses its continuation lines too (e.g. a requirements list spread over several
    lines), so no stale items survive. (Before 2026-11-16 the FIRST match won even when commented:
    in a spec with both `#android.api = 31` and `android.api = 34`, that made a duplicate key.)"""
    pattern = re.compile(rf'^[ \t]*(#?)[ \t]*{re.escape(key)}[ \t]*=[^\n]*', re.M)
    line = f'{key} = {value}'
    found = list(pattern.finditer(text))
    m = next((x for x in found if not x.group(1)), found[0] if found else None)
    if m:
        end = m.end()
        if not m.group(1):
            end = re.compile(CONT).match(text, end).end()
        return text[:m.start()] + line + text[end:]
    return re.sub(r'^\[app\][ \t]*$', f'[app]\n{line}', text, count=1, flags=re.M)


def current(text: str, key: str) -> str | None:
    """The uncommented value of key, continuation lines joined (one line, items kept)."""
    m = re.search(rf'^[ \t]*{re.escape(key)}[ \t]*=([^\n]*{CONT})', text, re.M)
    if not m:
        return None
    lines = m.group(1).split('\n')
    keep = lines[:1] + [x for x in lines[1:] if not x.strip().startswith(('#', ';'))]  # drop indented comments
    return ' '.join(' '.join(keep).split())


def append_items(text: str, key: str, value: str) -> tuple[str, str]:
    old = current(text, key)
    items = [i.strip() for i in (old or '').split(',') if i.strip()]
    for item in (i.strip() for i in value.split(',')):
        if item and item not in items:
            items.append(item)
    return ', '.join(items), old or ''


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    spec = sys.argv[1]
    # read bytes-exact line endings, work on LF, write back in the file's own style (CRLF stays CRLF)
    with open(spec, encoding='utf-8', newline='') as f:
        text = f.read()
    nl = '\r\n' if '\r\n' in text else '\n'
    text = text.replace('\r\n', '\n')
    for key, value in parse(sys.argv[2:]):
        if key.endswith('+'):
            key = key[:-1].strip()
            value, old = append_items(text, key, value)
            print(f'append {key}: {old!r} -> {value!r}')
        text = patch(text, key, value)
        print(f'set {key} = {value}')
    with open(spec, 'w', encoding='utf-8', newline='') as f:
        f.write(text.replace('\n', nl))


if __name__ == '__main__':
    main()
