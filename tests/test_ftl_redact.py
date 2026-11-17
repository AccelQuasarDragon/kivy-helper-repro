# Run: uv run --no-project tests/test_ftl_redact.py
"""Regression guard for tools/ftl_redact.py (stdlib only, fake values, temp files only;
the fake email is built from parts so the privacy check does not flag it).

The filter (stdin -> stdout) and --inplace must replace the service account, project id, the project
NUMBER found as projects/<n>/ anywhere in WIF (not inside a longer number) and any test-lab-<x> bucket
name. Also: empty / unset values replace nothing, regex metacharacters in a value are literal, and
non-UTF-8 bytes pass through unchanged. Exit 0 = all pass, 1 = a failure."""
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
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
