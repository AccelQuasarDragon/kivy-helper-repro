"""Redact Google Cloud identifiers from devicelab.yml output (stdlib only).

Values come from env (the job's repo secrets): SA (service account email), PROJECT (project id),
WIF (...projects/<NUMBER>/locations/...: the project NUMBER is parsed from it). Any Test Lab bucket name
(test-lab-<anything>) is redacted too. Replacements (no later rule can re-match them): <redacted-sa>,
<redacted-project>, <redacted-number>, <redacted-bucket>. Empty / unset values are skipped.

Then generic rules for any text result (Test Lab's logcat names its throwaway device account):
  any email address -> <email> (same regex as tools/privacy_check.py; also masked ones and HAL names like
  <name>@1.0-service.pixel); the LOCAL PART (user name) of each email found anywhere in the file set is also
  replaced as a whole word -> <account> (two passes; only from a mail / account domain:
  its last label is letters only and not a file/HAL suffix (NOT_MAIL deny list), no digit-first label; skipped: < 4 chars, placeholders made of x / dots, a few common words);
  /home/<name> (privacy_check's home-path rule, the home dir "user" kept) -> /home/<home>. No value is ever printed.

  python3 tools/ftl_redact.py < raw.log > public.log     # filter, line by line (live output)
  python3 tools/ftl_redact.py --inplace FILE...          # rewrite files in place
  python3 tools/ftl_redact.py --check FILE...            # exit 1 if any raw value is left; prints file:line: kind only
"""
import os
import re
import sys

BUCKET = re.compile(rb'test-lab-[A-Za-z0-9_-]+')
NUMBER = re.compile(r'projects/([0-9]+)/')  # same rule as devicelab.yml's mask step
EMAIL = re.compile(rb'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')  # = tools/privacy_check.py EMAIL
HOME = re.compile(rb'/home/(?!user(?![A-Za-z0-9._-]))[A-Za-z0-9._-]+')  # = privacy_check home-path
PLACEHOLDER = re.compile(rb'[xX.]+')
COMMON = {b'user', b'root', b'admin', b'test', b'android', b'system', b'shell', b'runner', b'noreply', b'info',
          b'python', b'framework', b'base', b'classes', b'boot'}
# user names are collected from emails whose domain looks like a mail domain: the last label is letters only and
# NOT a file/HAL suffix (deny list), so country domains (.de, .co.uk) count, while file names that match the email
# regex (dalvik-cache "system at framework at boot.art", "base.apk at classes.dex", HAL names at
# "1.0-service.pixel") never qualify
NOT_MAIL = {b'dex', b'art', b'apk', b'jar', b'so', b'oat', b'odex', b'vdex', b'pixel', b'service', b'xml', b'json',
            b'txt', b'log', b'png', b'jpg', b'kv', b'py', b'pyc', b'zip', b'gz', b'bin', b'img', b'prop', b'rc'}


def usernames(data: bytes) -> set:
    """Local parts of the emails in data that are worth redacting elsewhere (lowercased)."""
    out = set()
    for m in EMAIL.finditer(data):
        local, _, domain = m.group().partition(b'@')
        local, labels = local.lower(), domain.lower().split(b'.')
        last = labels[-1]
        if not last.isalpha() or last in NOT_MAIL or any(not lb or lb[:1].isdigit() for lb in labels):
            continue
        if len(local) < 4 or PLACEHOLDER.fullmatch(local) or local in COMMON:
            continue
        out.add(local)
    return out


def name_rule(names):
    """One case-insensitive whole-word rule for these user names (longest first), or None."""
    if not names:
        return None
    alt = b'|'.join(re.escape(n) for n in sorted(names, key=lambda n: (-len(n), n)))
    return re.compile(rb'(?<![A-Za-z0-9_])(?:' + alt + rb')(?![A-Za-z0-9_])', re.I)


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


def redact_env(data: bytes, rs) -> bytes:
    for rx, repl in rs:
        data = rx.sub(repl, data)
    return data


def redact(data: bytes, rs, names=None) -> bytes:
    """rs (the env + bucket rules) first, so the service account keeps its own label; then the generic rules.
    names: a compiled name_rule (two-pass callers), False (none) or None (= the names found in data itself)."""
    data = redact_env(data, rs)
    if names is None:
        names = name_rule(usernames(data))
    data = EMAIL.sub(b'<email>', data)
    if names:
        data = names.sub(b'<account>', data)
    return HOME.sub(b'/home/<home>', data)


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
        # pass 1: read every file, collect the user names of all emails in the whole set; pass 2: rewrite
        datas = {}
        for path in argv[1:]:
            if os.path.isfile(path):
                with open(path, 'rb') as f:
                    datas[path] = f.read()
        found = set()
        for data in datas.values():
            found |= usernames(redact_env(data, rs))
        names = name_rule(found) or False
        for path, data in datas.items():
            with open(path, 'wb') as f:
                f.write(redact(data, rs, names))
        return 0
    if argv:
        sys.stderr.write(__doc__)
        return 2
    # filter: line by line (live output); user names seen so far apply to every later line
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    found, names = set(), False
    for line in iter(inp.readline, b''):
        new = usernames(redact_env(line, rs)) - found
        if new:
            found |= new
            names = name_rule(found)
        out.write(redact(line, rs, names))
        out.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
