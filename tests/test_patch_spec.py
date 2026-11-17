# Run: uv run --no-project tests/test_patch_spec.py
"""Regression guard for tools/patch_spec.py (stdlib only, deterministic, temp files only).

Cases: CRLF specs (append to [app], CRLF kept), LF stays LF, a trailing indented comment is not
swallowed, a comment between continuation lines, and a spec shaped like a real report's root spec
(commented `#android.api = 31` above `android.api = 34`, a multi-line requirements list), in LF
and CRLF: overrides must replace the UNCOMMENTED key and leave no duplicate (configparser strict).
Exit 0 = all pass, 1 = a failure (each case prints PASS / FAIL)."""
import configparser
import os
import subprocess
import sys
import tempfile

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, 'tools', 'patch_spec.py')
# mimics the layout of a real root spec (yabb85/controlP at cad5d5c): comments above set keys,
# requirements over several lines, keys in [app] and [buildozer]
REAL_LAYOUT = """[app]
title = Demo
source.dir = src
# (list) Application requirements
requirements = python3,
    kivy==2.3.2,
    https://github.com/kivymd/KivyMD/archive/master.zip,
    pillow,
    lxml==6.1.3
orientation = portrait
# (int) Target Android API, should be as high as possible.
#android.api = 31
android.api = 34
# (list) The Android archs to build for
#android.archs = arm64-v8a, armeabi-v7a
android.archs = arm64-v8a
p4a.branch = develop

[buildozer]
log_level = 2
warn_on_root = 1
"""
ok = True


def run(tmp, name, text, args, newline='\n'):
    p = os.path.join(tmp, name)
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text.replace('\n', newline))
    subprocess.run([sys.executable, TOOL, p, *args], check=True, capture_output=True)
    with open(p, encoding='utf-8', newline='') as f:
        return f.read()


def check(cond, msg):
    global ok
    print(('PASS ' if cond else 'FAIL ') + msg)
    ok = ok and bool(cond)


def load(text):
    c = configparser.ConfigParser(allow_no_value=True, interpolation=None)  # strict: a duplicate key raises
    c.read_string(text.replace('\r\n', '\n'))
    return c


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = run(tmp, 'crlf.spec', '[app]\ntitle = t\n[buildozer]\nlog_level = 1\n', ['android.api=36', 'log_level=2'], '\r\n')
        check(out.count('\r\n') == out.count('\n') and 'android.api = 36\r\n' in out, 'CRLF: key appended to [app], every line still CRLF')
        c = load(out)
        check(c.get('app', 'android.api') == '36' and c.get('buildozer', 'log_level') == '2', 'CRLF: loads, both values set')
        out = run(tmp, 'lf.spec', '[app]\ntitle = t\n', ['android.api=36'])
        check('\r' not in out and 'android.api = 36\n' in out, 'LF: stays LF')
        out = run(tmp, 'cmt.spec', '[app]\nrequirements = a,\n    b\n    # keep this comment\nnext.key = 1\n', ['requirements+=c'])
        check('    # keep this comment' in out and load(out).get('app', 'requirements') == 'a, b, c',
              'trailing indented comment kept; requirements+=c gives a, b, c')
        out = run(tmp, 'mid.spec', '[app]\nrequirements = a,\n    # mid comment\n    b\nx = 1\n', ['requirements=z'])
        c = load(out)
        check(c.get('app', 'requirements') == 'z' and c.get('app', 'x') == '1', 'comment between continuation lines: replaced as one value')
        for nl, tag in (('\n', 'LF'), ('\r\n', 'CRLF')):
            out = run(tmp, f'real_{tag}.spec', REAL_LAYOUT,
                      ['android.api=36', 'requirements+=requests', 'android.archs+=x86_64', 'warn_on_root=0', 'source.dir=.'], nl)
            try:
                c = load(out)
                good = (c.get('app', 'android.api') == '36' and c.get('app', 'android.archs') == 'arm64-v8a, x86_64'
                        and c.get('app', 'requirements').endswith('lxml==6.1.3, requests')
                        and c.get('app', 'source.dir') == '.' and c.get('buildozer', 'warn_on_root') == '0'
                        and '#android.api = 31' in out and (nl == '\n' or out.count('\r\n') == out.count('\n')))
            except configparser.Error as e:
                good = False
                print('   configparser:', e)
            check(good, f'real layout ({tag}): api 36 on the uncommented key, archs + x86_64, requests appended, no duplicates')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
