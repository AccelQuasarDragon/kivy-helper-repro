# /// script
# requires-python = '>=3.10'
# dependencies = []
# ///
"""controlP top-down bisect as a RULE (stdlib only), plus its dispatch JSON. Docs: docs/bisect.md.

A variant = a point (groups off, ripple toggle values, shadows on/off); patches/controlp/bisect_toggles.diff
reads the groups + toggles from app_config.json. Every variant builds their app at the pinned commit with
demo_device + [shadows_on +] bisect_toggles: shadows on = shadows_on.diff in the list (the TopView BoxShadows
draw), shadows off = as controlP ships (it disables shadows).
app_config = every GROUP key always (so B0-B5 keep their exact JSON) + a toggle key only when it differs from
its default (_bisect.py fills a missing key with its default: omitted = shipped).
The variant list itself is the plan's choice of splits (no rule produces it), so it is a small table of points;
B5 is written as B2 plus the transition, not repeated.

  uv run --no-project tools/controlp_bisect.py [--only B1,B3]
      -> matrix.yml `builds` JSON (B0-B5 by default, or the listed ones, e.g. --only S0,T1,T2,W)
  uv run --no-project tools/controlp_bisect.py RUN_ID RUN_NUMBER [--attempt N] [--only B1]
      -> per variant: one inspect.yml gate JSON line, then one devicelab.yml JSON line
         (RUN_ID = the matrix run's ID from its URL, RUN_NUMBER = its #n)
Output holds only run ids, artifact names and labels.
"""
import argparse
import json
import sys
from typing import NamedTuple

REPO = 'yabb85/controlP'
REF = 'cad5d5c626516dcbf18719194c92e63f06128d62'
DEMO, SHADOWS, TOGGLES = ('patches/controlp/demo_device.diff', 'patches/controlp/shadows_on.diff',
                          'patches/controlp/bisect_toggles.diff')
PATCHES = (DEMO, SHADOWS, TOGGLES)  # shadows on
PATCHES_SHIPPED = (DEMO, TOGGLES)   # shadows off = as controlP ships
# MIRRORS DEFAULTS in bisect_toggles.diff's _bisect.py (tests/test_controlp_bisect.py checks it)
DEFAULTS = {'input_fx': True, 'menu': True, 'bottom': True, 'topbar': True, 'transition': '',
            'ripple_fbo_fs': '', 'ripple_stencil': True, 'list_ripple': True}
GROUPS = ('input_fx', 'menu', 'bottom', 'topbar', 'transition')  # the off-set axis; the other DEFAULTS keys = toggles
OFF = {'input_fx': False, 'menu': False, 'bottom': False, 'topbar': False, 'transition': 'No'}


class Variant(NamedTuple):
    off: frozenset = frozenset()  # groups switched off (each to OFF[group])
    toggles: tuple = ()           # ((key, value), ...): ripple toggles set away from their default, DEFAULTS order
    shadows: bool = True          # True = shadows_on.diff in the patch list


def point(*off: str, shadows: bool = True, **toggles) -> Variant:
    unknown = set(off) - set(GROUPS) | set(toggles) - (set(DEFAULTS) - set(GROUPS))
    assert not unknown, f'unknown group/toggle {unknown}'
    order = list(DEFAULTS).index
    return Variant(frozenset(off), tuple(sorted(toggles.items(), key=lambda kv: order(kv[0]))), shadows)


VARIANTS = {'B0': point(), 'B1': point('input_fx', 'menu'),
            'B2': point('input_fx', 'menu', 'bottom', 'topbar'),
            'B3': point('input_fx'), 'B4': point('menu')}
VARIANTS['B5'] = VARIANTS['B2']._replace(off=VARIANTS['B2'].off | {'transition'})
VARIANTS.update({
    'S0': point(shadows=False),         # the reporter's shipped config: is the BoxShadow Fbo needed?
    'T1': point(ripple_fbo_fs='create'),  # is the ripple Fbo's late shader set (the kivy#8098 pattern) needed?
    'T2': point(ripple_stencil=False),    # is the ripple's stencil mask needed?
    'W': point(list_ripple=False),      # workaround candidate: every list ripple off
})
DEFAULT_RUN = ('B0', 'B1', 'B2', 'B3', 'B4', 'B5')  # no --only = the top-down round (output as before)
# Home: a blank MDLabel spacer (dismisses an open shade, unverified); then DL1's taps (input, row, explore)
TAPS = '540,2000,5;540,600,8;540,800,8;540,360,8;540,360,10'
GATE = {'launch_wait': '45', 'api_level': '35'}
DEVICE = {'device': 'redfin', 'version': '30', 'timeout': '5m'}


def app_config(name: str) -> dict:
    v = VARIANTS[name]
    cfg = {k: OFF[k] if k in v.off else DEFAULTS[k] for k in GROUPS}
    cfg.update(v.toggles)
    return cfg


def word(value) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def describe(name: str) -> str:
    v = VARIANTS[name]
    off = sorted(v.off, key=list(DEFAULTS).index)
    parts = (['+'.join(off) + ' off'] if off else []) + [f'{k}={word(val)}' for k, val in v.toggles]
    return f'{name} ' + (' '.join(parts) or 'defaults')


def shadows_word(name: str) -> str:
    return 'shadows on' if VARIANTS[name].shadows else 'shadows off'


def patches(name: str) -> tuple:
    return PATCHES if VARIANTS[name].shadows else PATCHES_SHIPPED


def matrix(names) -> list[dict]:
    return [{
        'name': n,
        'label': f'controlP bisect {describe(n)} (demo device, {shadows_word(n)})',
        'repo': REPO, 'ref': REF, 'app': 'src',
        'patches': ';'.join(patches(n)),
        'app_config': app_config(n),
        'extra': 'android.api=34',
        'add_archs': 'x86_64',  # fat APK: the same file runs the x86_64 gate and the arm64 phone
        'cache': 'off',
    } for n in names]


def artifact(run_number: int, name: str, attempt: int) -> str:
    return f'build-{run_number}-{name}-a{attempt}'


def run_label(name: str) -> str:
    """describe() + ' shadows off' when off (shadows on is the B norm; their labels stay as they were)."""
    return describe(name) + ('' if VARIANTS[name].shadows else ' ' + shadows_word(name))


def gate(run_id: str, run_number: int, name: str, attempt: int = 1) -> dict:
    return {'label': f'controlP bisect gate {run_label(name)} from matrix run {run_id}',
            'artifact_run': run_id, 'artifact_name': artifact(run_number, name, attempt),
            'taps': TAPS, **GATE}


def devicelab(run_id: str, run_number: int, name: str, attempt: int = 1) -> dict:
    return {'label': f'controlP bisect {run_label(name)} from matrix run {run_id} on Pixel 5 Android 11',
            'artifact_run': run_id, 'artifact_name': artifact(run_number, name, attempt),
            'taps': TAPS, **DEVICE}


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('run_id', nargs='?')
    ap.add_argument('run_number', nargs='?', type=int)
    ap.add_argument('--attempt', type=int, default=1)
    ap.add_argument('--only', default='',
                    help=f'comma list of variants (default {",".join(DEFAULT_RUN)}; known {",".join(VARIANTS)})')
    a = ap.parse_args(argv)
    names = [n.strip() for n in a.only.split(',') if n.strip()] or list(DEFAULT_RUN)
    bad = [n for n in names if n not in VARIANTS]
    if bad:
        ap.error(f'unknown variant(s) {bad}; known {list(VARIANTS)}')
    dump = lambda x: json.dumps(x, separators=(',', ':'))  # noqa: E731
    if a.run_id is None:
        print(dump(matrix(names)))
        return 0
    if not a.run_id.isdigit() or a.run_number is None:
        ap.error('give RUN_ID (digits) and RUN_NUMBER')
    for n in names:
        print(dump(gate(a.run_id, a.run_number, n, a.attempt)))
        print(dump(devicelab(a.run_id, a.run_number, n, a.attempt)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
