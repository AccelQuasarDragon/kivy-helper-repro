# Run: uv run --no-project tests/test_ftl_redact.py
"""Regression guard for tools/ftl_redact.py (stdlib only, fake values, temp files only;
the fake email is built from parts so the privacy check does not flag it).

The filter (stdin -> stdout) and --inplace must replace the service account, project id, the project
NUMBER found as projects/<n>/ anywhere in WIF (not inside a longer number) and any test-lab-<x> bucket
name. Also: empty / unset values replace nothing, regex metacharacters in a value are literal, and
non-UTF-8 bytes pass through unchanged. Generic rules: any email -> <email> (masked ones and
HAL names too), the user names of those emails as whole words -> <account> (filter: from earlier lines;
--inplace: two passes over the whole file set), /home/<name> -> /home/<home> (user kept); nothing printed.
Exit 0 = all pass, 1 = a failure."""
import os
import subprocess
import sys
import tempfile

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, 'tools', 'ftl_redact.py')
BASE = {k: v for k, v in os.environ.items() if k not in ('SA', 'PROJECT', 'WIF')}
ENV = dict(BASE, PROJECT='demo-proj-42', SA='ftl-runner' + '@' + 'demo-proj-42.iam.gserviceaccount.com',
           WIF='projects/123456789012/locations/global/workloadIdentityPools/p/providers/q')
RAW = ('API not enabled in project 123456789012.\n'
       'Raw results: https://console.developers.google.com/storage/browser/test-lab-ab12cd34-xyz/2026-11-17_x/\n'
       'gs://test-lab-ab12cd34-xyz/2026-11-17_x/redfin-30-en-portrait/logcat as ' + ENV['SA'] + '\n'
       'project demo-proj-42; other number 91234567890123 stays\n')
WANT = ('API not enabled in project <redacted-number>.\n'
        'Raw results: https://console.developers.google.com/storage/browser/<redacted-bucket>/2026-11-17_x/\n'
        'gs://<redacted-bucket>/2026-11-17_x/redfin-30-en-portrait/logcat as <redacted-sa>\n'
        'project <redacted-project>; other number 91234567890123 stays\n')


def run(data: bytes, env) -> bytes:
    return subprocess.run([sys.executable, TOOL], input=data, capture_output=True, env=env, check=True).stdout


def check(name, got, want):
    print(('PASS' if got == want else 'FAIL') + ' ' + name + ('' if got == want else f': {got!r}'))
    return got == want


def main() -> int:
    ok = check('filter', run(RAW.encode(), ENV).decode(), WANT)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'logcat')
        with open(p, 'wb') as f:
            f.write(RAW.encode())
        subprocess.run([sys.executable, TOOL, '--inplace', p, os.path.join(d, 'missing.log')], check=True, env=ENV)
        with open(p, 'rb') as f:
            ok &= check('--inplace', f.read().decode(), WANT)
        # --check: the redacted file is clean; a raw file fails with file:line: kind, never the value
        c = subprocess.run([sys.executable, TOOL, '--check', p], capture_output=True, text=True, env=ENV)
        ok &= check('--check redacted = exit 0', (c.returncode, c.stdout), (0, ''))
        raw = os.path.join(d, 'raw.log')
        with open(raw, 'wb') as f:
            f.write(b'\xff clean\n' + RAW.encode())
        c = subprocess.run([sys.executable, TOOL, '--check', raw], capture_output=True, text=True, env=ENV)
        ok &= check('--check raw = exit 1', c.returncode, 1)
        ok &= check('--check names line 2 number', f'{raw}:2: raw redacted-number value left' in c.stdout, True)
        ok &= check('--check prints no value', any(v in c.stdout + c.stderr for v in
                    ('demo-proj-42', '123456789012', 'test-lab-ab12')), False)
        c = subprocess.run([sys.executable, TOOL, '--check', raw], capture_output=True, text=True,
                           env=dict(BASE, SA='', PROJECT='', WIF=''))
        lines = c.stdout.splitlines()
        ok &= check('--check empty env: only the bucket rule', bool(lines) and all('bucket' in ln for ln in lines), True)
        c = subprocess.run([sys.executable, TOOL, '--check', os.path.join(d, 'missing.log')], capture_output=True,
                           text=True, env=ENV)
        ok &= check('--check missing file = exit 1', c.returncode, 1)
    # WIF with the //iam.googleapis.com/ prefix: the number is still found
    iam = dict(ENV, WIF='//iam.googleapis.com/' + ENV['WIF'])
    ok &= check('WIF with iam prefix', run(b'in project 123456789012\n', iam), b'in project <redacted-number>\n')
    # unset and empty values: nothing but the bucket rule applies (no "" replaced everywhere)
    text = b'abc 123456789012 demo-proj-42 test-lab-q1\n'
    ok &= check('env unset', run(text, BASE), b'abc 123456789012 demo-proj-42 <redacted-bucket>\n')
    ok &= check('env empty', run(text, dict(BASE, SA='', PROJECT='', WIF='')),
                b'abc 123456789012 demo-proj-42 <redacted-bucket>\n')
    # metacharacters are literal: "demo.p+1" must not match "demoXpp1"
    meta = dict(BASE, PROJECT='demo.p+1')
    ok &= check('regex metacharacters', run(b'demoXpp1 demo.p+1\n', meta), b'demoXpp1 <redacted-project>\n')
    # non-UTF-8 bytes pass through unchanged around a redaction
    ok &= check('non-UTF-8 input', run(b'\xff\xfe test-lab-x9 \x80\n', BASE), b'\xff\xfe <redacted-bucket> \x80\n')
    ok &= generic_rules()
    return 0 if ok else 1


# generic rules (emails, their user names, /home/<name>): fake values built from parts (AT, HOME) so
# tools/privacy_check.py does not flag this file itself
AT, HOME = '@', '/ho' + 'me/'
LAB = 'fakelab' + 'acct77'
GEN_RAW = ('I AccountHelper: added ' + LAB + AT + 'labaccounts.example.com\n'
           'I Auth: masked x' + AT + 'xxxx.xxx and xxxxxx' + AT + 'xxxx.xxx\n'
           'I init: starting composer' + AT + '1.0-service.pixel\n'
           'I App: open ' + HOME + 'alice/app/main.py and ' + HOME + 'user/app and ' + HOME + 'runner/work\n')
GEN_RAW2 = ('I AccountHelper: account: ' + LAB + ' synced\n'
            'I App: ' + LAB.upper() + ' and ' + LAB + 'x and bob ' + LAB + '.\n')
GEN_WANT = ('I AccountHelper: added <email>\n'
            'I Auth: masked <email> and <email>\n'
            'I init: starting <email>\n'
            'I App: open ' + HOME + '<home>/app/main.py and ' + HOME + 'user/app and ' + HOME + '<home>/work\n')
GEN_WANT2 = ('I AccountHelper: account: <account> synced\n'
             'I App: <account> and ' + LAB + 'x and bob <account>.\n')


def generic_rules() -> bool:
    ok = check('filter: email, masked, HAL, home', run(GEN_RAW.encode(), BASE).decode(), GEN_WANT)
    # filter mode: a user name seen on an earlier line is redacted alone on a later line (whole word only)
    ok &= check('filter: user name on a later line', run((GEN_RAW + GEN_RAW2).encode(), BASE).decode(),
                GEN_WANT + GEN_WANT2)
    # short / placeholder / HAL local parts are never collected as user names
    ok &= check('no short / placeholder / HAL names', run(b'composer xxxxxx xx\n' + GEN_RAW.encode(), BASE).decode(),
                'composer xxxxxx xx\n' + GEN_WANT)
    with tempfile.TemporaryDirectory() as d:
        # --inplace two-pass: the email is in file a, the bare user name in file b (and before the email in a)
        a, b = os.path.join(d, 'logcat'), os.path.join(d, 'other.txt')
        with open(a, 'wb') as f:
            f.write(GEN_RAW2.encode() + GEN_RAW.encode())
        with open(b, 'wb') as f:
            f.write(b'\xff\x00 ' + LAB.encode() + b' \x80\n')
        c = subprocess.run([sys.executable, TOOL, '--inplace', a, b], capture_output=True, env=ENV)
        ok &= check('--inplace prints nothing', (c.returncode, c.stdout, c.stderr), (0, b'', b''))
        with open(a, 'rb') as f:
            ok &= check('--inplace two-pass, same file', f.read().decode(), GEN_WANT2 + GEN_WANT)
        with open(b, 'rb') as f:
            ok &= check('--inplace two-pass, other file, binary-safe', f.read(), b'\xff\x00 <account> \x80\n')
        # the redacted files pass tools/privacy_check.py --files
        pc = os.path.join(os.path.dirname(TOOL), 'privacy_check.py')
        c = subprocess.run([sys.executable, pc, '--files', a, b], capture_output=True, text=True, env=BASE, cwd=d)
        ok &= check('privacy_check passes the redacted files', (c.returncode, c.stdout), (0, ''))
    # file names that match the email regex are redacted where they stand but collect NO user name:
    # Java frame paths and the "I python :" tag lines (the summary greps them) survive elsewhere
    files = ('W art: /data/dalvik-cache/arm64/system' + AT + 'framework' + AT + 'boot.art\n'
             'W art: /data/app/base.apk' + AT + 'classes.dex\n'
             'I main: python' + AT + 'run.so\n')
    keep = ('at /system/framework/framework.jar (boot) base.apk classes\n'
            'I python  : [INFO   ] [Kivy        ] v2.3.2\n')
    ok &= check('file names collect no user name', run((files + keep).encode(), BASE).decode().split('\n', 3)[3], keep)
    # the lab-style account domain still collects the name
    lab = 'labby' + 'user9'
    ok &= check('lab account domain collects the name',
                run(('a ' + lab + AT + 'cloudtestlab' + 'accounts.com\nb ' + lab + '\n').encode(), BASE),
                b'a <email>\nb <account>\n')
    return ok


if __name__ == '__main__':
    sys.exit(main())
