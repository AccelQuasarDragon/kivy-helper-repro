"""Redact Google Cloud identifiers from devicelab.yml output (stdlib only).

Values come from env (the job's repo secrets): SA (service account email), PROJECT (project id),
WIF (...projects/<NUMBER>/locations/...: the project NUMBER is parsed from it). Any Test Lab bucket name
(test-lab-<anything>) is redacted too. Replacements (no later rule can re-match them): <redacted-sa>,
<redacted-project>, <redacted-number>, <redacted-bucket>. Empty / unset values are skipped.

  python3 tools/ftl_redact.py < raw.log > public.log     # filter, line by line (live output)
  python3 tools/ftl_redact.py --inplace FILE...          # rewrite files in place
  python3 tools/ftl_redact.py --check FILE...            # exit 1 if any raw value is left; prints file:line: kind only
"""
import os
import re
import sys

BUCKET = re.compile(rb'test-lab-[A-Za-z0-9_-]+')
NUMBER = re.compile(r'projects/([0-9]+)/')  # same rule as devicelab.yml's mask step


def rules(env=os.environ):
    out = []
    for key, repl in (('SA', b'<redacted-sa>'), ('PROJECT', b'<redacted-project>')):  # SA first: it holds the id
        if env.get(key):
            out.append((re.compile(re.escape(env[key].encode())), repl))
    m = NUMBER.search(env.get('WIF', ''))
    if m:
        out.append((re.compile(rb'(?<![0-9])' + m[1].encode() + rb'(?![0-9])'), b'<redacted-number>'))
    out.append((BUCKET, b'<redacted-bucket>'))
    return out


def redact(data: bytes, rs) -> bytes:
    for rx, repl in rs:
        data = rx.sub(repl, data)
    return data


def main(argv) -> int:
    rs = rules()
    if argv[:1] == ['--check']:
        bad = 0
        for path in argv[1:]:
            try:
                with open(path, 'rb') as f:
                    data = f.read()
            except OSError:
                print(f'{path}: unreadable')
                bad += 1
                continue
            for n, line in enumerate(data.split(b'\n'), 1):
                for rx, repl in rs:
                    if rx.search(line):
                        print(f'{path}:{n}: raw {repl.decode().strip("<>")} value left')  # never the value
                        bad += 1
        print(f'ftl_redact --check: {bad} hit(s); files={len(argv) - 1}', file=sys.stderr)
        return 1 if bad else 0
    if argv[:1] == ['--inplace']:
        for path in argv[1:]:
            if os.path.isfile(path):
                with open(path, 'rb') as f:
                    data = f.read()
                with open(path, 'wb') as f:
                    f.write(redact(data, rs))
        return 0
    if argv:
        sys.stderr.write(__doc__)
        return 2
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    for line in iter(inp.readline, b''):
        out.write(redact(line, rs))
        out.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
