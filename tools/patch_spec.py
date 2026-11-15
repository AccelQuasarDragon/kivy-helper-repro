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


def patch(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf'^[ \t]*#?[ \t]*{re.escape(key)}[ \t]*=.*$', re.M)
    line = f'{key} = {value}'
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    return re.sub(r'^\[app\][ \t]*$', f'[app]\n{line}', text, count=1, flags=re.M)


def current(text: str, key: str) -> str | None:
    m = re.search(rf'^[ 	]*{re.escape(key)}[ 	]*=(.*)$', text, re.M)
    return m.group(1).strip() if m else None


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
    with open(spec, encoding='utf-8') as f:
        text = f.read()
    for key, value in parse(sys.argv[2:]):
        if key.endswith('+'):
            key = key[:-1].strip()
            value, old = append_items(text, key, value)
            print(f'append {key}: {old!r} -> {value!r}')
        text = patch(text, key, value)
        print(f'set {key} = {value}')
    with open(spec, 'w', encoding='utf-8') as f:
        f.write(text)


if __name__ == '__main__':
    main()
