# Run: uv run --no-project tests/test_controlp_bisect.py
"""Regression guard for patches/controlp/bisect_toggles.diff + tools/controlp_bisect.py (stdlib only).

1. Patches (needs network + git; SKIP with a message when offline): a pristine LF checkout of their
   pinned commit (shallow fetch into a temp dir, never run), then git apply demo_device, shadows_on,
   bisect_toggles in that order; also with insets_fix after them. py_compile of _bisect.py + main.py;
   _bisect.py's DEFAULTS == the generator's DEFAULTS.
2. Generator invariants: B0 = defaults; B1..B5 switch off exactly the plan's groups; every build has
   all 3 patches in order (shadows_on included); matrix.yml accepts the elements (keys, names, 1-8);
   gate / devicelab JSON point at build-<number>-<name>-a<attempt> with the same taps.
Exit 0 = all pass (a SKIP passes), 1 = a failure."""
import ast
import os
import py_compile
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import controlp_bisect as cb  # noqa: E402

PATCH = {n: os.path.join(ROOT, 'patches', 'controlp', n + '.diff')
         for n in ('demo_device', 'shadows_on', 'bisect_toggles', 'insets_fix')}
ok = True


def check(cond, msg):
    global ok
    print(('PASS ' if cond else 'FAIL ') + msg)
    ok = ok and bool(cond)


def git(*args, cwd):
    return subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=cwd, capture_output=True, text=True)


def defaults_of(path):
    tree = ast.parse(open(path, encoding='utf-8').read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'DEFAULTS' for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def fetch(tmp):
    """Pristine checkout of the pinned commit in tmp/<name>; None when offline."""
    src = os.path.join(tmp, 'controlp')
    os.makedirs(src)
    for args in (('init', '-q'), ('fetch', '-q', '--depth', '1', f'https://github.com/{cb.REPO}', cb.REF),
                 ('checkout', '-q', 'FETCH_HEAD')):
        r = git(*args, cwd=src)
        if r.returncode:
            print(f'SKIP patch checks (offline or fetch failed): git {args[0]}: {r.stderr.strip()[:200]}')
            return None
    return src


def patch_checks():
    with tempfile.TemporaryDirectory() as tmp:
        src = fetch(tmp)
        if src is None:
            return
        check(git('rev-parse', 'HEAD', cwd=src).stdout.strip() == cb.REF, f'checkout is {cb.REF[:7]}')
        order = ('demo_device', 'shadows_on', 'bisect_toggles')
        for name in order:
            r = git('apply', '--verbose', PATCH[name], cwd=src)
            check(r.returncode == 0, f'git apply {name}.diff' + ('' if not r.returncode else ': ' + r.stderr.strip()[:300]))
        r = git('apply', '--check', PATCH['insets_fix'], cwd=src)
        check(r.returncode == 0, 'insets_fix.diff still applies on top of the 3')
        bis = os.path.join(src, 'src', 'controlp', '_bisect.py')
        main = os.path.join(src, 'src', 'main.py')
        for f in (bis, main):
            try:
                py_compile.compile(f, cfile=os.path.join(tmp, 'x.pyc'), doraise=True)
                check(True, f'py_compile {os.path.basename(f)}')
            except py_compile.PyCompileError as e:
                check(False, f'py_compile {os.path.basename(f)}: {e}')
        text = open(main, encoding='utf-8').read()
        check(text.count('import controlp._bisect') == 1 and '# disable_shadows()' in text,
              'main.py: one bisect import, shadows_on still in effect')
        check(defaults_of(bis) == cb.DEFAULTS, f'_bisect.py DEFAULTS == generator DEFAULTS {cb.DEFAULTS}')


def matrix_defaults():
    text = open(os.path.join(ROOT, '.github', 'workflows', 'matrix.yml'), encoding='utf-8').read()
    m = re.search(r'^( *)DEFAULTS = (\{.*?\})\s*$', text, re.M | re.S)
    return ast.literal_eval(re.sub(r'\n\s+', ' ', m.group(2)))


def generator_checks():
    expect = {'B0': set(), 'B1': {'input_fx', 'menu'}, 'B2': {'input_fx', 'menu', 'bottom', 'topbar'},
              'B3': {'input_fx'}, 'B4': {'menu'}, 'B5': {'input_fx', 'menu', 'bottom', 'topbar', 'transition'}}
    check(list(cb.VARIANTS) == list(expect), f'variants {list(expect)}')
    builds = {b['name']: b for b in cb.matrix(list(cb.VARIANTS))}
    check(builds['B0']['app_config'] == cb.DEFAULTS, 'B0 app_config = defaults')
    for name, off in expect.items():
        cfg = builds[name]['app_config']
        got = {k for k, v in cfg.items() if v != cb.DEFAULTS[k]}
        check(got == off and all(cfg[k] == cb.OFF[k] for k in off), f'{name} off-set {sorted(off)}')
        check(builds[name]['patches'].split(';') == list(cb.PATCHES), f'{name} patches: demo_device;shadows_on;bisect_toggles')
        check(builds[name]['ref'] == cb.REF and builds[name]['app'] == 'src' and
              builds[name]['extra'] == 'android.api=34' and builds[name]['add_archs'] == 'x86_64',
              f'{name} repo/ref/app/extra/add_archs')
    allowed = set(matrix_defaults()) | {'name'}
    check(all(set(b) <= allowed for b in builds.values()), 'matrix.yml knows every key')
    check(1 <= len(builds) <= 8 and all(re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', n) for n in builds),
          'matrix.yml: 1-8 builds, valid names')
    check(len(set(b['label'] for b in builds.values())) == len(builds), 'labels distinct')
    g, d = cb.gate('123', 7, 'B3', 2), cb.devicelab('123', 7, 'B3', 2)
    check(g['artifact_name'] == d['artifact_name'] == 'build-7-B3-a2' and g['artifact_run'] == '123',
          'gate + devicelab artifact = build-<number>-<name>-a<attempt>')
    check(g['taps'] == d['taps'] and g['taps'].startswith('540,2000,5;540,600,8;'), 'same taps, prefix then DL1')
    check(d['device'] == 'redfin' and d['version'] == '30' and g['launch_wait'] == '45' and g['api_level'] == '35',
          'device redfin/30, gate launch_wait 45 api 35')
    check(defaults_of(os.path.join(ROOT, 'tools', 'controlp_bisect.py')) is not None, 'generator DEFAULTS is a literal')


def main() -> int:
    generator_checks()
    patch_checks()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
