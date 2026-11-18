# Run: uv run --no-project tests/test_card_page.py
"""Regression guard for tools/card_page.py report features (stdlib only, temp dirs only, fake run ids):
- free text: md() output is byte-identical to the frozen pre-PR-5 md() on a corpus (escaping unchanged);
- dead links: a run's card page (shots/<id>/) is linked only when shots/<id>/index.html exists;
- diagram: good flowcharts pass; each rejected pattern (click / href / call, %%{, script: / data: URLs, URLs,
  HTML tags, backticks, @{, url(, &#, size, first line) is refused; HTML escapes it, TESTS.md fences it;
- CSP: no diagram = no script at all; a diagram = only the pinned Mermaid file (with SRI) + the hashed init;
- media opt-in: `media` without "cleared": true (missing, false, "true") is refused; good media -> plan;
- summary: rendered ABOVE the title in both views; code escaped / fenced; proof runs must be in runs;
- phone folders (devicelab.json): all screenshots + strip + video shown; embed can use a phone PNG; a listed
  file that is missing or a bad fact is refused.
Set TEST_CARD_PAGE=path to run it against another card_page.py (fail-first check on an older copy).
Exit 0 = all pass, 1 = a failure."""
import base64
import hashlib
import html
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
TOOL = os.environ.get('TEST_CARD_PAGE') or os.path.join(ROOT, 'tools', 'card_page.py')
spec = importlib.util.spec_from_file_location('card_page', TOOL)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)
REPO, SLUG = 'Owner-x/repo-y', 'test-report'
PIN = {'artifact': 'devicelab-10-a1', 'digest': 'sha256:' + '0123456789abcdef' * 4}
FAILS = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f' ({detail})' if detail and not cond else ''))
    if not cond:
        FAILS.append(name)


def raises(name, fn, want=''):
    try:
        fn()
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        check(name, want in str(exc), f'error was: {exc}')
        return
    check(name, False, 'no error raised')


# ---- frozen copy of md() as of the commit before PR 5 (e5b3c0f): free-text escaping must not change ----
_PUNCT = set('\\`*_{}[]()#+-.!|~$')
_ZW = '​'


def md_frozen(text, n=0):
    text = cp.short(text, n) if n else ' '.join(str(text).split())
    ent = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}
    out = ''.join(ent.get(c) or ('\\' + c if c in _PUNCT else c) for c in text)
    out = out.replace(':', ':' + _ZW).replace('@', '@' + _ZW)
    return re.sub(r'(?i)(www)(?=\\\.)', r'\1' + _ZW, out)


CORPUS = ['plain', '<script>alert(1)</script>', '[x](https://evil.example)', 'a|b|c', '`code`', '$x$ math',
          'see www.example.com or https://x.example/a?b=c', 'mail a' + '@' + 'b.example', '# not a heading', '**bold** _it_',
          '```mermaid\nflowchart TD\n```', 'line1\nline2\ttab', '&amp; "q" \'s\'', '\\ back \\\\', '~strike~ {x}',
          '<br/> <img src=x onerror=alert(1)>', 'flowchart TD click A href "javascript:alert(1)"', 'x' * 500]


def run_cli(args):
    r = subprocess.run([sys.executable, '-I', TOOL] + args, capture_output=True, text=True, encoding='utf-8')
    return r.returncode, r.stdout, r.stderr


def write(path, data, mode='w'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as f:
        f.write(data)


PNG_1PX = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
GOOD_DIAGRAM = '''flowchart TD
  A["S0 · 101<br/>shadows off<br>CRASH"] --> B{"T1 · 102<br />CLEAN"}
  B -. crash .-> C["not run"]
  B -- "clean: late shader needed" --> D
  C <--> D
  classDef notrun stroke-dasharray: 5 5,color:#888;
  class C notrun;
  %% a plain comment is fine'''

BAD_DIAGRAMS = {
    'click': 'flowchart TD\n  A --> B\n  click A "x"',
    'href': 'flowchart TD\n  A --> B\n  A href "x"',
    'call': 'flowchart TD\n  A --> B\n  click A call f()',
    'init directive': '%%{init: {"securityLevel": "loose"}}%%\nflowchart TD\n  A --> B',
    'init directive later': 'flowchart TD\n  %%{init: {"securityLevel": "loose"}}%%\n  A --> B',
    'javascript: URL': 'flowchart TD\n  A["javascript:alert(1)"] --> B',
    'vbscript: URL': 'flowchart TD\n  A["VBScript :x"] --> B',
    'data: URL': 'flowchart TD\n  A["data:text/html,x"] --> B',
    'https URL': 'flowchart TD\n  A["https://evil.example"] --> B',
    'www': 'flowchart TD\n  A["www.evil.example"] --> B',
    'HTML tag img': 'flowchart TD\n  A["<img src=x onerror=alert(1)>"] --> B',
    'HTML tag script': 'flowchart TD\n  A["<script>x</script>"] --> B',
    'HTML closing tag': 'flowchart TD\n  A["</pre>"] --> B',
    'HTML comment': 'flowchart TD\n  A["<!-- x -->"] --> B',
    'backtick markdown string': 'flowchart TD\n  A["`**x**`"] --> B',
    '@{ shape / img': 'flowchart TD\n  A@{ img: "x.png" } --> B',
    'url( in style': 'flowchart TD\n  A --> B\n  style A fill:url(#x)',
    'entity &#': 'flowchart TD\n  A["&#106;avascript"] --> B',
    'control char': 'flowchart TD\n  A["x\x01"] --> B',
    'not a flowchart': 'sequenceDiagram\n  A->>B: hi',
    'frontmatter config': '---\nconfig:\n  securityLevel: loose\n---\nflowchart TD\n  A --> B',
    'empty': '   \n  ',
    'too long': 'flowchart TD\n' + '  A --> B\n' * 900,
    'not text': ['flowchart TD'],
    'entity code #name;': 'flowchart TD\n  A["#lt;img#gt;"] --> B',
    'entity code #123;': 'flowchart TD\n  A["#60;b#62;"] --> B',
    'hex colour outside a style line': 'flowchart TD\n  A["#888;"] --> B',
    'protocol-relative URL': 'flowchart TD\n  A["//evil.example/x"] --> B',
}


def base_spec(**extra):
    s = {'title': 'T <b>', 'description': 'D', 'image': 'https://github.com/x.png',
         'runs': [{'id': 101, 'label': 'inspect run'}, {'id': 202, 'label': 'phone run'}]}
    s.update(extra)
    return s


def render_all(tmp, spec_obj, shots=None, embed=False):
    spec_path = os.path.join(tmp, 'spec.json')
    write(spec_path, json.dumps(spec_obj))
    out, md_out = os.path.join(tmp, 'index.html'), os.path.join(tmp, 'TESTS.md')
    args = [out, '--spec', spec_path, '--repo', REPO, '--slug', SLUG, '--md', md_out]
    if shots:
        args += ['--shots-root', shots, '--sheet-manifest', os.path.join(tmp, 'm.json')]
    if embed:
        args += ['--embed-manifest', os.path.join(tmp, 'e.json')]
    rc, so, se = run_cli(args)
    if rc:
        return rc, se, ''
    with open(out, encoding='utf-8') as f, open(md_out, encoding='utf-8') as g:
        return rc, f.read(), g.read()


def main():
    # ---- free-text escaping unchanged ----
    check('md() identical to the frozen pre-PR-5 md() on the corpus',
          all(cp.md(t) == md_frozen(t) for t in CORPUS) and cp.md(CORPUS[-1], 50) == md_frozen(CORPUS[-1], 50))

    # ---- diagram validation ----
    check('good diagram (br forms, dotted / labelled / <--> edges, classDef, comment) passes',
          cp.validate_diagram(GOOD_DIAGRAM) == GOOD_DIAGRAM)
    check('graph LR passes', bool(cp.validate_diagram('graph LR\n  A --> B')))
    check('hex colours on style / classDef / linkStyle lines pass', bool(cp.validate_diagram(
        'flowchart TD\n  A --> B\n  style A fill:#f9f,stroke:#333\n  classDef x color:#2b6cb0;\n  linkStyle 0 stroke:#ff3;')))
    for name, src in BAD_DIAGRAMS.items():
        raises(f'diagram rejected: {name}', lambda src=src: cp.validate_diagram(src))
    raises('section diagram validated in the spec', lambda: cp.validate(base_spec(sections=[{'heading': 'h', 'diagram': BAD_DIAGRAMS['click']}])),
           'section 1 diagram')

    # ---- media opt-in ----
    for name, media in [('no cleared', {'images': 'all', 'video': True}), ('cleared false', {'cleared': False}),
                        ('cleared "true" (a string)', {'cleared': 'true', 'video': True}),
                        ('cleared 1', {'cleared': 1, 'video': True}), ('not an object', True)]:
        raises(f'media refused: {name}', lambda m=media: cp.validate(base_spec(runs=[{'id': 202, 'media': m}])),
               'media')
    for name, bad in [('no artifact', {'digest': PIN['digest']}), ('no digest', {'artifact': PIN['artifact']}),
                      ('apk artifact', dict(PIN, artifact='devicelab-apk-10-a1')),
                      ('digest not sha256', dict(PIN, digest='md5:' + 'a' * 32)), ('digest short', dict(PIN, digest='sha256:abc')),
                      ('replace not bool', dict(PIN, replace='yes'))]:
        raises(f'media refused: {name}', lambda b=bad: cp.validate(base_spec(runs=[{'id': 202, 'media': dict(b, cleared=True, video=True)}])))
    raises('media refused: unknown key', lambda: cp.validate(base_spec(runs=[{'id': 202, 'media': dict(PIN, cleared=True, **{'logcat': True})}])),
           'unknown key')
    raises('media refused: frames without video', lambda: cp.validate(base_spec(runs=[{'id': 202, 'media': dict(PIN, cleared=True, **{'frames': 4})}])),
           'frames')
    raises('media refused: bad image name', lambda: cp.validate(base_spec(runs=[{'id': 202, 'media': dict(PIN, cleared=True, **{'images': ['../x.png']})}])),
           'images')
    raises('media refused: nothing to publish', lambda: cp.validate(base_spec(runs=[{'id': 202, 'media': dict(PIN, cleared=True, **{'images': []})}])),
           'nothing')
    with tempfile.TemporaryDirectory() as tmp:
        write(os.path.join(tmp, 's.json'), json.dumps(base_spec(runs=[{'id': 101}, {'id': 202, 'media': dict(PIN, cleared=True, video=True)}])))
        rc, so, se = run_cli(['--spec', os.path.join(tmp, 's.json'), '--run-ids', '--media-plan', os.path.join(tmp, 'p.json')])
        plan = json.load(open(os.path.join(tmp, 'p.json'))) if rc == 0 else None
        check('media plan = the cleared run only (images all, video, 8 frames)',
              plan == [dict(PIN, images='all', video=True, frames=8, replace=False, id='202')], f'rc={rc} {se} {plan}')
        write(os.path.join(tmp, 's2.json'), json.dumps(base_spec(runs=[{'id': 202, 'media': {'video': True}}])))
        rc, so, se = run_cli(['--spec', os.path.join(tmp, 's2.json'), '--run-ids', '--media-plan', os.path.join(tmp, 'p2.json')])
        check('--run-ids refuses media without "cleared": true', rc == 2 and 'cleared' in se, f'rc={rc} {se}')
        # M2: an already published folder is kept unless replace is true
        shots = os.path.join(tmp, 'shotsrc')
        write(os.path.join(shots, 'shots', '202', 'devicelab.json'), '{}')
        for replace, want in [(False, []), (True, ['202'])]:
            write(os.path.join(tmp, 's3.json'), json.dumps(base_spec(runs=[{'id': 202, 'media': dict(PIN, cleared=True, video=True, replace=replace)}])))
            rc, so, se = run_cli(['--spec', os.path.join(tmp, 's3.json'), '--run-ids', '--media-plan', os.path.join(tmp, 'p3.json'),
                                  '--shots-root', shots])
            got = [x['id'] for x in json.load(open(os.path.join(tmp, 'p3.json')))] if rc == 0 else None
            check(f'published shots/202/ + replace={replace}: plan {want}' + (' + a notice' if not replace else ''),
                  got == want and (replace or 'notice: run 202: media already published' in se), f'rc={rc} {se} {got}')
        write(os.path.join(tmp, 's2.json'), json.dumps(base_spec(runs=[{'id': 202, 'media': {'cleared': True, 'video': True}}])))
        rc, so, se = run_cli(['--spec', os.path.join(tmp, 's2.json'), '--run-ids', '--media-plan', os.path.join(tmp, 'p2.json')])
        check('--run-ids refuses media without artifact + digest (exit 2, nothing written)',
              rc == 2 and 'artifact' in se and not os.path.exists(os.path.join(tmp, 'p2.json')), f'rc={rc} {se}')

    # ---- summary ----
    summ = {'bug': 'late <shader>', 'fix': 'pass fs= at creation', 'code': 'self.fbo = Fbo(fs=fs)\n# </pre><script>x</script> ```',
            'lang': 'python', 'proof': 'Phone runs:', 'proof_runs': [202]}
    raises('summary: proof run not in runs', lambda: cp.validate(base_spec(summary=dict(summ, proof_runs=[999]))), 'not in runs')
    raises('summary: needs a proof link', lambda: cp.validate(base_spec(summary=dict(summ, proof_runs=[])), ), 'proof')
    raises('summary: needs bug', lambda: cp.validate(base_spec(summary=dict(summ, bug=''))), 'bug')
    raises('summary: unknown key', lambda: cp.validate(base_spec(summary=dict(summ, extra=1))), 'unknown')
    raises('summary: bad lang', lambda: cp.validate(base_spec(summary=dict(summ, lang='py thon'))), 'lang')

    with tempfile.TemporaryDirectory() as tmp:
        shots = os.path.join(tmp, 'shotsrc')
        write(os.path.join(shots, 'shots', '101', '00_launch.png'), PNG_1PX, 'wb')
        write(os.path.join(shots, 'shots', '101', 'index.html'), '<!doctype html>', 'w')
        ph = os.path.join(shots, 'shots', '202')
        for n in ('0.png', '2.png', '10.png', 'frame_01.png', 'strip.png', 'sheet.png'):
            write(os.path.join(ph, n), PNG_1PX, 'wb')
        write(os.path.join(ph, 'video.mp4'), b'\x00\x00\x00\x18ftypisom', 'wb')
        rec = {'workflow': 'devicelab.yml', 'run_id': '202', 'images': ['0.png', '2.png', '10.png'], 'frames': ['frame_01.png'],
               'video': 'video.mp4', 'strip': 'strip.png', 'sheet': 'sheet.png', 'notes': [],
               'facts': {'device': 'redfin-30-en-portrait', 'outcome': 'Failed', 'details': 'Application crashed',
                         'test_time_s': 88, 'screenshots': 3, 'video_s': 91.5, 'crash_files': 2, 'taps': 5}}
        write(os.path.join(ph, 'devicelab.json'), json.dumps(rec))
        sp = base_spec(summary=summ, sections=[{'heading': 'flow', 'diagram': GOOD_DIAGRAM}],
                       embed=[{'run': 202, 'image': '2.png', 'caption': 'phone'}])
        rc, page, tests = render_all(tmp, sp, shots, embed=True)
        check('report with summary + diagram + phone folder renders', rc == 0, page if rc else '')
        if rc == 0:
            run_page = f'https://owner-x.github.io/repo-y/shots/'
            # dead links
            check('dead link skipped: no index.html -> no shots/202/ link (HTML)', f'href="{run_page}202/"' not in page)
            check('dead link skipped: no index.html -> no shots/202/ link (TESTS.md)', f'({run_page}202/)' not in tests)
            check('existing run card linked: shots/101/index.html -> link (HTML + TESTS.md)',
                  f'href="{run_page}101/"' in page and f'({run_page}101/)' in tests)
            # summary above the title
            check('summary above the title (HTML)', page.index('class="summary"') < page.index('<h1>'))
            check('summary above the title (TESTS.md)', tests.startswith('1. **Bug:**') and tests.index('2. **Fix:**') < tests.index('\n# T'))
            check('summary code escaped in HTML (no raw tag)', '<script>x</script>' not in page and '&lt;/pre&gt;&lt;script&gt;' in page)
            check('summary code fenced in TESTS.md (fence longer than ```)', '   ````python\n   self.fbo = Fbo(fs=fs)' in tests)
            check('summary proof links the run', f'https://github.com/{REPO}/actions/runs/202' in page.split('<h1>')[0])
            check('summary free text still md-escaped', '2. **Fix:** ' + cp.md('pass fs= at creation') in tests and
                  '1. **Bug:** ' + cp.md('late <shader>') in tests)
            # diagram views
            check('diagram in HTML: escaped inside <pre class="mermaid">',
                  f'<pre class="mermaid">{html.escape(GOOD_DIAGRAM, quote=True)}</pre>' in page)
            check('diagram in TESTS.md: ```mermaid fence', f'```mermaid\n{GOOD_DIAGRAM}\n```' in tests)
            init_hash = base64.b64encode(hashlib.sha256(cp.MERMAID_INIT.encode()).digest()).decode()
            check('pinned Mermaid script with SRI + crossorigin',
                  f'<script src="{cp.MERMAID_URL}" integrity="{cp.MERMAID_SRI}" crossorigin="anonymous"></script>' in page
                  and re.fullmatch(r'https://cdn\.jsdelivr\.net/npm/mermaid@\d+\.\d+\.\d+/dist/mermaid\.min\.js', cp.MERMAID_URL))
            check('CSP allows only that file + the hashed inline init',
                  html.escape(f"script-src {cp.MERMAID_URL} 'sha256-{init_hash}';", quote=True) in page
                  and f'<script>{cp.MERMAID_INIT}</script>' in page and page.count('<script') == 2)
            # phone folder
            for n in ('0.png', '2.png', '10.png'):
                check(f'phone screenshot {n} on index.html and TESTS.md',
                      f'/shots/shots/202/{n}' in page and f'/shots/shots/202/{n}' in tests)
            check('phone screenshots in number order (2 before 10)', page.index('/202/2.png') < page.index('/202/10.png'))
            check('video element (Pages URL) + strip on index.html',
                  f'<video controls preload="metadata" playsinline src="{run_page}202/video.mp4"></video>' in page
                  and '/shots/shots/202/strip.png' in page)
            check('TESTS.md phone section: strip, sheet, video link',
                  '### Phone run 202' in tests and '202/strip.png' in tests and '202/sheet.png' in tests and
                  f'({run_page}202/video.mp4)' in tests and '(#phone-run-202)' in tests)
            check('phone facts: "--" details never shown', cp.phone_line({'phone': {'facts': {'outcome': 'Passed', 'details': '--'}}})
                  == 'Phone run (Firebase Test Lab): Test Lab outcome Passed')
            check('phone facts line', 'Test Lab outcome Failed (Application crashed)' in page and 'test time 88 s' in page)
            emb = json.load(open(os.path.join(tmp, 'e.json')))
            check('embed can use a phone screenshot', len(emb) == 1 and emb[0]['images'][0].endswith(os.path.join('202', '2.png')))
            man = json.load(open(os.path.join(tmp, 'm.json')))
            check('sheet defaults skip strip.png / sheet.png', all(not p.endswith(('strip.png', 'sheet.png')) for g in man for p in g['images']))

        # no diagram: no script at all
        rc, page, _ = render_all(tmp, base_spec(), shots)
        check('no diagram: CSP script-src none and no <script>', rc == 0 and "script-src &#x27;none&#x27;" in page and '<script' not in page)
        csp = page.split('Content-Security-Policy" content="', 1)[1].split('"', 1)[0] if rc == 0 else ''
        check('CSP img-src / media-src = raw.githubusercontent.com + the Pages host only (no https:, no github.com)',
              'img-src https://raw.githubusercontent.com https://accelquasardragon.github.io https://owner-x.github.io;' in csp
              and 'media-src https://raw.githubusercontent.com https://accelquasardragon.github.io https://owner-x.github.io;' in csp
              and 'https:;' not in csp and 'github.com ' not in csp.replace('githubusercontent.com', ''), csp)

        # bad devicelab.json
        write(os.path.join(ph, 'devicelab.json'), json.dumps(dict(rec, images=['0.png', '5.png'])))
        rc, err, _ = render_all(tmp, base_spec(), shots)
        check('devicelab.json listing a missing file is refused', rc == 2 and '5.png' in err, err)
        write(os.path.join(ph, 'devicelab.json'), json.dumps(dict(rec, facts={'device': '<script>'})))
        rc, err, _ = render_all(tmp, base_spec(), shots)
        check('devicelab.json with a bad fact is refused', rc == 2 and 'fact' in err, err)
        write(os.path.join(ph, 'devicelab.json'), json.dumps(dict(rec, video='../x.mp4')))
        rc, err, _ = render_all(tmp, base_spec(), shots)
        check('devicelab.json with a bad video name is refused', rc == 2 and 'video' in err, err)
        write(os.path.join(ph, 'devicelab.json'), json.dumps(dict(rec, run_id='999')))
        rc, err, _ = render_all(tmp, base_spec(), shots)
        check('devicelab.json of another run is refused', rc == 2 and 'devicelab.json' in err, err)

    print(f'{len(FAILS)} failure(s)')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
