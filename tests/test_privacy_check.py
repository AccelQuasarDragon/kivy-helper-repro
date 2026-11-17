# Run: uv run --no-project tests/test_privacy_check.py
"""Regression guard for tools/privacy_check.py (stdlib only, temp files only).

home-path: ANY /home/<name> is a hit, also inside a relative path (tar / zip listings, backup copies);
only the container's own /home/user stays allowed. A false positive (controlP's relative kv path:
home.kv in folder views/home; built from parts below) is cleared by a narrow .privacy-allow rule, never by weakening the rule.
--files: plain files outside git, .privacy-allow applies (the inline marker does not), the value is never printed.
An allow line clears only the spans its regex matches; the rest of the line is still scanned.
Exit 0 = all pass, 1 = a failure."""
import importlib.util
import os
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
TOOL = os.path.join(ROOT, 'tools', 'privacy_check.py')
spec = importlib.util.spec_from_file_location('privacy_check', TOOL)
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

# built from parts so this file does not match the rule itself
H = '/' + 'home/'
HIT = [H + 'alice/x', '"' + H + 'bob"', 'HOME=' + H + 'carol', 'cd ' + H + 'dave', "'" + H + 'erin/a.py',
       '(' + H + 'frank)', '`' + H + 'gina`', 'path:' + H + 'hal', H + 'users',
       'file://' + H + 'alice/a.py', '/var' + H + 'bob', '/c/msys64' + H + 'carl/x', '/mnt' + H + 'eve',
       '//' + H + 'dan',
       # relative paths holding a home dir: tar / zip listings, backup copies
       '.' + H + 'alice/x', 'backup' + H + 'alice/a.py']
NO_HIT = [H + 'user', H + 'user/app', '"' + H + 'user/.buildozer"']
KV = 'views' + H + 'home.kv'
ALLOW = r'shots/final-report-2026-11-15/*:(?<![\w./-])views/hom[e]/home\\?\.kv'  # same line as .privacy-allow
REPORT = 'shots/final-report-2026-11-15/TESTS.md'
EMAIL = 'bob' + '@' + 'example.org'
TOKEN = 'gh' + 'p_' + 'A' * 24


def home_hit(line):
    return any(r == 'home-path' for r, _ in pc.line_hits(line))


def left(allow, path, line):
    """rules still hit after the allow spans are removed"""
    return [r for r, _ in pc.line_hits(pc.strip_allowed(allow, path, line))]


def check(name, cond):
    print(('PASS' if cond else 'FAIL') + ' ' + name)
    return cond


def main() -> int:
    ok = True
    for line in HIT:
        ok &= check(f'hit    {line!r}', home_hit(line))
    for line in NO_HIT:
        ok &= check(f'no hit {line!r}', not home_hit(line))
    # the allow mechanism, through a temp .privacy-allow: only the matched spans are cleared
    with tempfile.TemporaryDirectory() as d:
        ok &= check('kv path hits with no allow file', pc.load_allow(d) == [] and home_hit(KV))
        with open(os.path.join(d, pc.ALLOW_FILE), 'w', encoding='utf-8') as f:
            f.write('# comment\n' + ALLOW + '\n')
        allow = pc.load_allow(d)
        rule = pc.load_allow(ROOT)[0]
        ok &= check('repo .privacy-allow holds the same rule', rule[0] + ':' + rule[1].pattern == ALLOW)
        ok &= check('allow clears the plain kv path in its folder', left(allow, REPORT, 'see ' + KV) == [])
        ok &= check('allow clears the markdown-escaped kv path',
                    left(allow, REPORT, '(controlP: ' + KV.replace('.kv', '\\.kv') + ' lines') == [])
        ok &= check('allowed kv path + a real home dir on one line = hit',
                    'home-path' in left(allow, REPORT, 'see ' + KV + '; cd ' + H + 'alice'))
        both = left(allow, REPORT, 'see ' + KV + '; ' + EMAIL + ' ' + H + 'alice ' + TOKEN)
        ok &= check('allowed kv path + email, home dir, token = all hit',
                    {'email', 'home-path', 'github-token'} <= set(both))
        ok &= check('no left anchor match: x' + KV, 'home-path' in left(allow, REPORT, 'x' + KV))
        ok &= check('absolute path ending in the kv path = hit',
                    'home-path' in left(allow, REPORT, H + 'alice/controlP/' + KV))
        ok &= check('allow does not clear the kv path in another folder',
                    'home-path' in left(allow, 'shots/other/TESTS.md', 'see ' + KV))
        # --files: plain files, allow file read from the working directory, value never printed
        os.makedirs(os.path.join(d, 'shots', 'final-report-2026-11-15'))
        with open(os.path.join(d, REPORT), 'wb') as f:
            f.write(b'see ' + KV.encode() + b'\n\xff\xfe binary bytes\n')
        with open(os.path.join(d, 'log.txt'), 'wb') as f:
            f.write(b'ok line\ncd ' + (H + 'alice').encode() + b'/x\n')
        with open(os.path.join(d, 'marker.txt'), 'w', encoding='utf-8') as f:
            f.write('cd ' + H + 'alice  # ' + pc.MARKER + '\n')

        def run(*paths):
            return subprocess.run([sys.executable, TOOL, '--files', *paths], cwd=d, capture_output=True, text=True)
        p = run(REPORT)
        ok &= check('--files: allowed kv path + non-UTF-8 bytes = 0 hits', p.returncode == 0 and p.stdout == '')
        p = run(REPORT, 'log.txt')
        ok &= check('--files: real home dir = exit 1, file:line: rule',
                    p.returncode == 1 and p.stdout == 'log.txt:2: home-path\n')
        ok &= check('--files: value not printed', 'alice' not in p.stdout + p.stderr)
        p = run('marker.txt')
        ok &= check('--files: inline marker ignored (untrusted output)',
                    p.returncode == 1 and p.stdout == 'marker.txt:1: home-path\n')
        ok &= check('tree mode still honours the inline marker', not home_hit('cd ' + H + 'alice  # ' + pc.MARKER))
        p = run('missing.txt')
        ok &= check('--files: missing file = hit', p.returncode == 1 and 'unreadable' in p.stdout)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
