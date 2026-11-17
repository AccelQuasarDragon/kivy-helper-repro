# /// script
# requires-python = '>=3.10'
# dependencies = []
# ///
"""controlP top-down bisect as a RULE (stdlib only), plus its dispatch JSON. Docs: docs/bisect.md.

A variant = the SET of groups switched off (patches/controlp/bisect_toggles.diff reads them from
app_config.json). Every variant builds their app at the pinned commit with demo_device + shadows_on +
bisect_toggles (the TopView BoxShadows stay ON everywhere; shadows are tested last, outside this tool).
The variant list itself is the plan's choice of splits (no rule produces it), so it is a small table;
B5 is written as B2 plus the transition, not repeated.

  uv run --no-project tools/controlp_bisect.py [--only B1,B3]
      -> matrix.yml `builds` JSON (all variants, or the listed ones)
  uv run --no-project tools/controlp_bisect.py RUN_ID RUN_NUMBER [--attempt N] [--only B1]
      -> per variant: one inspect.yml gate JSON line, then one devicelab.yml JSON line
         (RUN_ID = the matrix run's ID from its URL, RUN_NUMBER = its #n)
Output holds only run ids, artifact names and labels.
"""
import argparse
import json
import sys

REPO = 'yabb85/controlP'
REF = 'cad5d5c626516dcbf18719194c92e63f06128d62'
PATCHES = ('patches/controlp/demo_device.diff', 'patches/controlp/shadows_on.diff',
           'patches/controlp/bisect_toggles.diff')
# MIRRORS DEFAULTS in bisect_toggles.diff's _bisect.py (tests/test_controlp_bisect.py checks it)
DEFAULTS = {'input_fx': True, 'menu': True, 'bottom': True, 'topbar': True, 'transition': ''}
OFF = {'input_fx': False, 'menu': False, 'bottom': False, 'topbar': False, 'transition': 'No'}
VARIANTS = {'B0': frozenset(), 'B1': frozenset({'input_fx', 'menu'}),
            'B2': frozenset({'input_fx', 'menu', 'bottom', 'topbar'}),
            'B3': frozenset({'input_fx'}), 'B4': frozenset({'menu'})}
VARIANTS['B5'] = VARIANTS['B2'] | {'transition'}
# Home: a blank MDLabel spacer (dismisses an open shade, unverified); then DL1's taps (input, row, explore)
TAPS = '540,2000,5;540,600,8;540,800,8;540,360,8;540,360,10'
GATE = {'launch_wait': '45', 'api_level': '35'}
DEVICE = {'device': 'redfin', 'version': '30', 'timeout': '5m'}


def app_config(name: str) -> dict:
    off = VARIANTS[name]
    return {k: OFF[k] if k in off else v for k, v in DEFAULTS.items()}


def describe(name: str) -> str:
    off = sorted(VARIANTS[name], key=list(DEFAULTS).index)
    return f'{name} ' + ('+'.join(off) + ' off' if off else 'defaults')


def matrix(names) -> list[dict]:
    return [{
        'name': n,
        'label': f'controlP bisect {describe(n)} (demo device, shadows on)',
        'repo': REPO, 'ref': REF, 'app': 'src',
        'patches': ';'.join(PATCHES),
        'app_config': app_config(n),
        'extra': 'android.api=34',
        'add_archs': 'x86_64',  # fat APK: the same file runs the x86_64 gate and the arm64 phone
        'cache': 'off',
    } for n in names]


def artifact(run_number: int, name: str, attempt: int) -> str:
    return f'build-{run_number}-{name}-a{attempt}'


def gate(run_id: str, run_number: int, name: str, attempt: int = 1) -> dict:
    return {'label': f'controlP bisect gate {describe(name)} from matrix run {run_id}',
            'artifact_run': run_id, 'artifact_name': artifact(run_number, name, attempt),
            'taps': TAPS, **GATE}


def devicelab(run_id: str, run_number: int, name: str, attempt: int = 1) -> dict:
    return {'label': f'controlP bisect {describe(name)} from matrix run {run_id} on Pixel 5 Android 11',
            'artifact_run': run_id, 'artifact_name': artifact(run_number, name, attempt),
            'taps': TAPS, **DEVICE}


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('run_id', nargs='?')
    ap.add_argument('run_number', nargs='?', type=int)
    ap.add_argument('--attempt', type=int, default=1)
    ap.add_argument('--only', default='', help='comma list of variants, e.g. B1,B3')
    a = ap.parse_args(argv)
    names = [n.strip() for n in a.only.split(',') if n.strip()] or list(VARIANTS)
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
