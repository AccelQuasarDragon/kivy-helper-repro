# Run: uv run --no-project tests/test_controlp_bisect.py
"""Regression guard for patches/controlp/bisect_toggles.diff + tools/controlp_bisect.py (stdlib only).

1. Patches (needs network + git; SKIP with a message when offline): a pristine LF checkout of their
   pinned commit (shallow fetch into a temp dir, never run), then git apply each patch set the generator
   uses, in order: demo_device;shadows_on;bisect_toggles (shadows on) AND demo_device;bisect_toggles
   (shadows off, as shipped); insets_fix still applies on top of each. py_compile of _bisect.py + main.py;
   _bisect.py's DEFAULTS == the generator's DEFAULTS.
2. Ripple patches (offline: _bisect.py read from the diff, ast only, no Kivy): the stencil-free M3
   lay_canvas_instructions adds the Fbo + Color + textured shape and no Stencil*; init_fbos passes fs= to Fbo()
   and never touches .shader. With network, against KivyMD a00c10c's ripple_behavior.py: the names widgets
   import (RectangularRippleBehavior / CircularRippleBehavior) are followed through the module-level aliases
   to the M3 classes, whose lay_canvas_instructions + init_fbos resolve to M3CommonRipple (the patched class);
   the patched methods equal the shipped ones (normalized ast) minus exactly the 6 stencil-related calls /
   minus set_shader with fs= added; set_shader is the only .fs assignment and only init_fbos calls it.
   Runtime evidence (Kivy + a display, not here): tools/ripple_runtime_check.py.
3. Generator invariants: B0 = defaults; B1..B5 switch off exactly the plan's groups; B0-B5 output is
   byte-identical to PR 4 (sha256 of the default matrix + gate/devicelab JSON); S0/T1/T2/W set the
   shadows axis + toggles; the patch list follows the shadows axis and labels say it; matrix.yml accepts
   the elements (keys, names, 1-8 per run); gate / devicelab JSON point at build-<number>-<name>-a<attempt>.
Exit 0 = all pass (a SKIP passes), 1 = a failure."""
import ast
import contextlib
import copy
import hashlib
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import controlp_bisect as cb  # noqa: E402

PATCH = {n: os.path.join(ROOT, 'patches', 'controlp', n + '.diff')
         for n in ('demo_device', 'shadows_on', 'bisect_toggles', 'insets_fix')}
KIVYMD = 'a00c10c385064afb3a46b3a10d1d2c0c6505dc48'  # KivyMD master read for the ripple patches
RIPPLE_URL = f'https://raw.githubusercontent.com/kivymd/KivyMD/{KIVYMD}/kivymd/uix/behaviors/ripple_behavior.py'
GRAPHICS = re.compile(r'^(Color|Ellipse|Rectangle|RoundedRectangle|Stencil(Push|Use|UnUse|Pop))$')
# PR 4 output (B0-B5), sha256 of: the default matrix JSON; the concatenated gate+devicelab JSON for run 123 #7 a2
GOLDEN_MATRIX = '7830efda1e79f1d067cdec68d8989491b325dbaf2a9bc966699ff89698858a8b'
GOLDEN_RUNS = '57a69b096561756c3da396be944bba32e01e66bacfb6587cde0a14494e49b5d7'
ok = True


def check(cond, msg):
    global ok
    print(('PASS ' if cond else 'FAIL ') + msg)
    ok = ok and bool(cond)


def git(*args, cwd):
    return subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=cwd, capture_output=True, text=True)


def defaults_of_tree(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'DEFAULTS' for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def defaults_of(path):
    return defaults_of_tree(ast.parse(open(path, encoding='utf-8').read()))


def bisect_source_from_diff() -> str:
    """_bisect.py as the diff adds it (the '+' lines of its new-file hunk)."""
    text = open(PATCH['bisect_toggles'], encoding='utf-8').read()
    hunk = text.split('+++ b/src/controlp/_bisect.py\n', 1)[1].split('\ndiff --git', 1)[0]
    return ''.join(line[1:] + '\n' for line in hunk.splitlines()[1:] if line.startswith('+'))


def fetch(tmp):
    """Pristine checkout of the pinned commit in tmp/<name>; None when offline."""
    src = os.path.join(tmp, 'controlp')
    os.makedirs(src)
    for args in (('init', '-q'), ('fetch', '-q', '--depth', '1', f'https://github.com/{cb.REPO}', cb.REF),
                 ('checkout', '-q', 'FETCH_HEAD')):
        r = git('-c', 'gc.auto=0', *args, cwd=src)
        if r.returncode:
            print(f'SKIP patch checks (offline or fetch failed): git {args[0]}: {r.stderr.strip()[:200]}')
            return None
    return src


def patch_set_checks(src, tmp, patches, shadows):
    tag = 'shadows on' if shadows else 'shadows off'
    git('checkout', '-q', '-f', 'FETCH_HEAD', cwd=src)
    git('clean', '-fdq', cwd=src)
    check(git('status', '--porcelain', cwd=src).stdout == '', f'[{tag}] pristine tree')
    for rel in patches:
        r = git('apply', '--verbose', os.path.join(ROOT, rel), cwd=src)
        check(r.returncode == 0, f'[{tag}] git apply {os.path.basename(rel)}' + ('' if not r.returncode else ': ' + r.stderr.strip()[:300]))
    r = git('apply', '--check', PATCH['insets_fix'], cwd=src)
    check(r.returncode == 0, f'[{tag}] insets_fix.diff still applies on top')
    bis = os.path.join(src, 'src', 'controlp', '_bisect.py')
    main = os.path.join(src, 'src', 'main.py')
    for f in (bis, main):
        try:
            py_compile.compile(f, cfile=os.path.join(tmp, 'x.pyc'), doraise=True)
            check(True, f'[{tag}] py_compile {os.path.basename(f)}')
        except py_compile.PyCompileError as e:
            check(False, f'[{tag}] py_compile {os.path.basename(f)}: {e}')
    text = open(main, encoding='utf-8').read()
    commented = '# disable_shadows()' in text
    called = re.search(r'^    disable_shadows\(\)$', text, re.M) is not None
    check(text.count('import controlp._bisect') == 1 and commented == shadows and called == (not shadows),
          f'[{tag}] main.py: one bisect import, disable_shadows() ' + ('commented out' if shadows else 'still called'))
    check(defaults_of(bis) == cb.DEFAULTS, f'[{tag}] _bisect.py DEFAULTS == generator DEFAULTS')
    check(open(bis, encoding='utf-8').read() == bisect_source_from_diff(), f'[{tag}] _bisect.py == the diff\'s + lines')


def patch_checks():
    with tempfile.TemporaryDirectory() as tmp:
        src = fetch(tmp)
        if src is None:
            return
        check(git('rev-parse', 'HEAD', cwd=src).stdout.strip() == cb.REF, f'checkout is {cb.REF[:7]}')
        check(cb.PATCHES == ('patches/controlp/demo_device.diff', 'patches/controlp/shadows_on.diff',
                             'patches/controlp/bisect_toggles.diff')
              and cb.PATCHES_SHIPPED == (cb.PATCHES[0], cb.PATCHES[2]), 'patch sets: with / without shadows_on')
        patch_set_checks(src, tmp, cb.PATCHES, shadows=True)
        patch_set_checks(src, tmp, cb.PATCHES_SHIPPED, shadows=False)


# ---- ripple patches: ast only ----
def call_name(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ''


def calls_in(fn):
    """Calls inside fn in source order."""
    return sorted((n for n in ast.walk(fn) if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))


def local_aliases(fn) -> set:
    """Local names bound only to graphics classes (`instr = Ellipse if shape_kind == 1.0 else RoundedRectangle`)."""
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            names = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)} - {'shape_kind'}
            if names and all(GRAPHICS.match(x) for x in names):
                out.add(n.targets[0].id)
    return out


def graphics(fn):
    alias = local_aliases(fn)
    return [c for c in calls_in(fn) if GRAPHICS.match(call_name(c)) or call_name(c) in alias]


def drop_stencil(calls):
    """Remove Stencil* calls and the shapes drawn between Push..Use (mask) and UnUse..Pop (unmask)."""
    keep, dropped, region = [], 0, False
    for c in calls:
        name = call_name(c)
        if name.startswith('Stencil'):
            dropped += 1
            region = name in ('StencilPush', 'StencilUnUse')
        elif region:
            dropped += 1
        else:
            keep.append(c)
    return keep, dropped


class Normalize(ast.NodeTransformer):
    """Make _bisect.py code comparable to KivyMD's: `rb.X` -> `X`, module constants (M3_GROUP) -> their value."""

    def __init__(self, consts):
        self.consts = consts

    def visit_Attribute(self, node):
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == 'rb':
            return ast.Name(id=node.attr, ctx=node.ctx)
        return node

    def visit_Name(self, node):
        return ast.Constant(self.consts[node.id]) if node.id in self.consts else node


def norm(node, consts=None) -> str:
    return ast.dump(Normalize(consts or {}).visit(copy.deepcopy(node)), annotate_fields=False)


def module_binding(tree, name):
    """The LAST module-level binding of `name`: a ClassDef, or (alias `name = Other`) what Other is bound to."""
    last = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            last = node
        elif isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == name for t in node.targets):
            last = node.value
    if isinstance(last, ast.Name):
        return module_binding(tree, last.id)
    return last


def find_method(tree, cls_name, meth):
    """(owner ClassDef, FunctionDef) of `meth` looked up from class `cls_name` (aliases followed, bases searched
    depth-first left to right: exact for this single-inheritance chain M3*Ripple -> M3CommonRipple -> CommonRipple)."""
    cls = module_binding(tree, cls_name)
    if not isinstance(cls, ast.ClassDef):
        return None, None
    for n in cls.body:
        if isinstance(n, ast.FunctionDef) and n.name == meth:
            return cls, n
    for b in cls.bases:
        if isinstance(b, ast.Name):
            owner, fn = find_method(tree, b.id, meth)
            if fn is not None:
                return owner, fn
    return None, None


def funcs(tree):
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def shipped_tree():
    try:
        with urllib.request.urlopen(RIPPLE_URL, timeout=30) as r:
            return ast.parse(r.read().decode('utf-8'))
    except Exception as e:  # noqa: BLE001
        print(f'SKIP shipped ripple comparison (offline or fetch failed): {e!r}'[:250])
        return None


def body_wo_doc(fn):
    return [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]


def ripple_checks():
    src = bisect_source_from_diff()
    tree = ast.parse(src)
    check(defaults_of_tree(tree) == cb.DEFAULTS, 'diff _bisect.py DEFAULTS == generator DEFAULTS (offline)')
    f = funcs(tree)
    consts = {'M3_GROUP': 'm3_ripple_behavior'}
    check(f"M3_GROUP = {consts['M3_GROUP']!r}" in src, 'M3_GROUP = the group M3 anim_complete removes')
    nost, init = f['m3_ripple_no_stencil'], f['m3_init_fbos_fs_at_create']
    names = [call_name(c) for c in graphics(nost)]
    check(names == ['Color', 'Ellipse', 'Rectangle'] and any(call_name(c) == 'add' for c in calls_in(nost)),
          f'm3_ripple_no_stencil: adds the Fbo, then {names} (no Stencil*, no mask shape)')
    fbo_calls = [c for c in calls_in(init) if call_name(c) == 'Fbo']
    check(len(fbo_calls) == 1 and 'fs' in {k.arg for k in fbo_calls[0].keywords}
          and not any(call_name(c) == 'set_shader' for c in calls_in(init))
          and not any(isinstance(n, ast.Attribute) and n.attr == 'shader' for n in ast.walk(init)),
          'm3_init_fbos_fs_at_create: Fbo(..., fs=...), no set_shader, no .shader access')
    check('rb.M3CommonRipple.init_fbos = m3_init_fbos_fs_at_create' in src, 'ripple_fbo_fs patches M3CommonRipple.init_fbos')
    check('rb.M3CommonRipple.lay_canvas_instructions = m3_ripple_no_stencil' in src,
          'ripple_stencil patches M3CommonRipple.lay_canvas_instructions')
    check('BaseListItem.__init__ = __init__' in src, 'list_ripple wraps BaseListItem.__init__ (class level)')
    check('ripple_dur' not in src and 'start_ripple' not in src, 'no ripple_dur left')
    first = [call_name(c) for c in calls_in(f['install'])]
    check(first.index('install_ripple') < first.index('schedule_once'), 'install_ripple runs at import, before on_start')
    shipped = shipped_tree()
    if shipped is None:
        return
    # the names the widgets import resolve, through the module-level aliases, to the M3 classes
    for alias, real in (('RectangularRippleBehavior', 'M3RectangularRippleBehavior'),
                        ('CircularRippleBehavior', 'M3CircularRippleBehavior')):
        cls = module_binding(shipped, alias)
        check(isinstance(cls, ast.ClassDef) and cls.name == real, f'shipped {alias} -> {getattr(cls, "name", cls)}')
        for meth in ('lay_canvas_instructions', 'init_fbos'):
            owner, _ = find_method(shipped, alias, meth)
            check(getattr(owner, 'name', None) == 'M3CommonRipple', f'{alias}.{meth} resolves to M3CommonRipple')
    _, lay = find_method(shipped, 'RectangularRippleBehavior', 'lay_canvas_instructions')
    keep, dropped = drop_stencil(graphics(lay))
    check(dropped == 6, f'shipped M3 lay_canvas_instructions: 6 stencil-related calls (got {dropped})')
    check([norm(c) for c in keep] == [norm(c, consts) for c in graphics(nost)],
          'm3_ripple_no_stencil == shipped M3 graphics minus stencil (same args + group)')
    adds = [[norm(x, c) for x in calls_in(fn) if call_name(x) == 'add'] for fn, c in ((lay, None), (nost, consts))]
    check(adds[0] == adds[1] != [], 'm3_ripple_no_stencil adds the same Fbo as shipped')
    params = [[norm(s, c) for s in ast.walk(fn) if isinstance(s, ast.Assign)
               and getattr(s.targets[0], 'id', '') in ('instr_params', 'shape_kind')] for fn, c in ((lay, None), (nost, consts))]
    check(params[0] == params[1] and len(params[0]) == 2, 'same instr_params + shape_kind as shipped')
    # init_fbos: shipped body minus set_shader, with fs= added to Fbo(), == the patched body minus its extras
    _, sinit = find_method(shipped, 'RectangularRippleBehavior', 'init_fbos')
    want = [copy.deepcopy(s) for s in body_wo_doc(sinit)
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and call_name(s.value) == 'set_shader')]
    for s in want:
        for n in ast.walk(s):
            if isinstance(n, ast.Call) and call_name(n) == 'Fbo':
                n.keywords.append(ast.keyword(arg='fs', value=ast.Name(id='RIPPLE_FS_STRING', ctx=ast.Load())))
    extras = (ast.If, ast.AugAssign)  # the shader-string load; the RIPPLE counter
    got = [s for s in body_wo_doc(init) if not (isinstance(s, extras) or
           (isinstance(s, ast.Assign) and getattr(s.targets[0], 'id', '') == 'rb'))]
    check([norm(s) for s in want] == [norm(s, consts) for s in got] and len(want) == len(body_wo_doc(sinit)) - 1,
          'm3_init_fbos_fs_at_create == shipped init_fbos with fs= at Fbo() and no set_shader')
    _, sshader = find_method(shipped, 'RectangularRippleBehavior', 'set_shader')
    s_if = [norm(s) for s in sshader.body if isinstance(s, ast.If)]
    p_if = [norm(s, consts) for s in init.body if isinstance(s, ast.If)]
    check(s_if == p_if != [], 'shader string loaded exactly as set_shader loads it')
    setters = [fn.name for fn in ast.walk(shipped) if isinstance(fn, ast.FunctionDef)
               for c in calls_in(fn) if call_name(c) == 'set_shader']
    fs_sets = [fn.name for fn in ast.walk(shipped) if isinstance(fn, ast.FunctionDef) for n in ast.walk(fn)
               if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == 'fs' for t in n.targets)]
    check(setters == ['init_fbos'] and fs_sets == ['set_shader'],
          f'shipped ripple_behavior.py: set_shader called only from {setters}, .fs assigned only in {fs_sets}')


# ---- generator ----
def matrix_defaults():
    text = open(os.path.join(ROOT, '.github', 'workflows', 'matrix.yml'), encoding='utf-8').read()
    m = re.search(r'^( *)DEFAULTS = (\{.*?\})\s*$', text, re.M | re.S)
    return ast.literal_eval(re.sub(r'\n\s+', ' ', m.group(2)))


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def generator_checks():
    dump = lambda x: json.dumps(x, separators=(',', ':'))  # noqa: E731
    groups5 = {'input_fx', 'menu', 'bottom', 'topbar'}
    expect = {'B0': (set(), {}, True), 'B1': ({'input_fx', 'menu'}, {}, True), 'B2': (groups5, {}, True),
              'B3': ({'input_fx'}, {}, True), 'B4': ({'menu'}, {}, True), 'B5': (groups5 | {'transition'}, {}, True),
              'S0': (set(), {}, False), 'T1': (set(), {'ripple_fbo_fs': 'create'}, True),
              'T2': (set(), {'ripple_stencil': False}, True), 'W': (set(), {'list_ripple': False}, True)}
    check(list(cb.VARIANTS) == list(expect), f'variants {list(expect)}')
    check(list(cb.DEFAULT_RUN) == ['B0', 'B1', 'B2', 'B3', 'B4', 'B5'], 'default run = B0-B5')
    check(set(cb.DEFAULTS) - set(cb.GROUPS) == {'ripple_fbo_fs', 'ripple_stencil', 'list_ripple'}, 'toggles = DEFAULTS minus GROUPS')
    check(sha(dump(cb.matrix(list(cb.DEFAULT_RUN)))) == GOLDEN_MATRIX, 'B0-B5 matrix JSON byte-identical to PR 4')
    runs = ''.join(dump(cb.gate('123', 7, n, 2)) + dump(cb.devicelab('123', 7, n, 2)) for n in cb.DEFAULT_RUN)
    check(sha(runs) == GOLDEN_RUNS, 'B0-B5 gate + devicelab JSON byte-identical to PR 4')
    builds = {b['name']: b for b in cb.matrix(list(cb.VARIANTS))}
    check(builds['B0']['app_config'] == {k: cb.DEFAULTS[k] for k in cb.GROUPS}, 'B0 app_config = group defaults')
    for name, (off, toggles, shadows) in expect.items():
        cfg = builds[name]['app_config']
        effective = {**cb.DEFAULTS, **cfg}  # what _bisect.py runs with (missing key = default)
        check(set(cfg) <= set(cb.DEFAULTS) and set(cb.GROUPS) <= set(cfg), f'{name} app_config keys: all groups + known toggles')
        got_off = {k for k in cb.GROUPS if effective[k] != cb.DEFAULTS[k]}
        got_tog = {k: v for k, v in effective.items() if k not in cb.GROUPS and v != cb.DEFAULTS[k]}
        check(got_off == off and all(cfg[k] == cb.OFF[k] for k in off) and got_tog == toggles,
              f'{name} off-set {sorted(off)} toggles {toggles}')
        want = cb.PATCHES if shadows else cb.PATCHES_SHIPPED
        check(builds[name]['patches'].split(';') == list(want),
              f'{name} patches: ' + ('demo_device;shadows_on;bisect_toggles' if shadows else 'demo_device;bisect_toggles'))
        word = 'shadows on' if shadows else 'shadows off'
        check(builds[name]['label'].endswith(f'(demo device, {word})'), f'{name} label says {word}')
        check(('shadows off' in cb.gate('1', 1, name)['label']) == (not shadows) and
              ('shadows off' in cb.devicelab('1', 1, name)['label']) == (not shadows), f'{name} gate/devicelab labels: shadows')
        check(builds[name]['ref'] == cb.REF and builds[name]['app'] == 'src' and
              builds[name]['extra'] == 'android.api=34' and builds[name]['add_archs'] == 'x86_64'
              and builds[name]['cache'] == 'off', f'{name} repo/ref/app/extra/add_archs/cache')
    allowed = set(matrix_defaults()) | {'name'}
    check(all(set(b) <= allowed for b in builds.values()), 'matrix.yml knows every key')
    for run in (list(cb.DEFAULT_RUN), ['S0', 'T1', 'T2', 'W']):
        check(1 <= len(run) <= 8, f'matrix.yml: 1-8 builds per run {run}')
    check(all(re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', n) for n in builds), 'matrix.yml: valid names')
    check(len(set(b['label'] for b in builds.values())) == len(builds), 'labels distinct')
    g, d = cb.gate('123', 7, 'T2', 2), cb.devicelab('123', 7, 'T2', 2)
    check(g['artifact_name'] == d['artifact_name'] == 'build-7-T2-a2' and g['artifact_run'] == '123',
          'gate + devicelab artifact = build-<number>-<name>-a<attempt>')
    check(g['taps'] == d['taps'] and g['taps'].startswith('540,2000,5;540,600,8;'), 'same taps, prefix then DL1')
    check(d['device'] == 'redfin' and d['version'] == '30' and g['launch_wait'] == '45' and g['api_level'] == '35',
          'device redfin/30, gate launch_wait 45 api 35')
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cb.main(['123', '7', '--only', 'S0,T1,T2,W'])
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    check(rc == 0 and len(lines) == 8 and [x['artifact_name'] for x in lines[::2]] ==
          ['build-7-S0-a1', 'build-7-T1-a1', 'build-7-T2-a1', 'build-7-W-a1'], 'gate/devicelab printing works for S0,T1,T2,W')
    check(defaults_of(os.path.join(ROOT, 'tools', 'controlp_bisect.py')) is not None, 'generator DEFAULTS is a literal')


def main() -> int:
    generator_checks()
    ripple_checks()
    patch_checks()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
