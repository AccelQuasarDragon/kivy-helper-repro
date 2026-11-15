# /// script
# requires-python = '>=3.10'
# dependencies = []
# ///
"""The Q-B bisection ladder as a RULE (stdlib only, no kivy import), plus its matrix.yml dispatch JSON.

A variant is a point (ui, extra):
  ui     kivy   = plain Kivy ScreenManager + SlideTransition + Button cards
         kivymd = MDScreenManager + MDSharedAxisTransition + elevated MDCard cards
  extra  plain  = nothing added (kivymd: shadows OFF, Factory's BoxShadow swapped for a no-op)
         fbo    = one raw Kivy Fbo widget added to screen 2
         shadow = every card carries a Kivy BoxShadow (kivy: drawn by us; kivymd: stock elevation)
Variants 1..5 = the product UIS x EXTRAS in that order, minus (kivymd, fbo). That one literal exception
keeps the ladder at the 5 slots the phone owner is asked to run; ui/extra can still be set directly.

Run `uv run --no-project stub_kivymd/ladder.py` to print the matrix.yml `builds` JSON for all 5.
"""
import json
import sys

UIS = ('kivy', 'kivymd')
EXTRAS = ('plain', 'fbo', 'shadow')
SKIP = {('kivymd', 'fbo')}  # outside the 5-slot budget (Q-B plan); a 6th test if ever allowed
UI_NAME = {'kivy': 'Kivy', 'kivymd': 'KivyMD'}
EXTRA_NAME = {'plain': 'plain', 'fbo': 'Fbo', 'shadow': 'BoxShadow'}


def variants() -> list[tuple[str, str]]:
    """Index n-1 = variant n."""
    return [(ui, ex) for ui in UIS for ex in EXTRAS if (ui, ex) not in SKIP]


def name(ui: str, extra: str) -> str:
    return f'{UI_NAME[ui]} {EXTRA_NAME[extra]}'


def resolve(variant: int, ui: str = '', extra: str = '') -> tuple[str, str]:
    """(ui, extra) for a variant number; explicit ui / extra override it."""
    vs = variants()
    if not 0 <= variant <= len(vs):
        raise ValueError(f'variant must be 0..{len(vs)}, got {variant}')
    base = vs[variant - 1] if variant > 0 else ('kivy', 'plain')
    ui, extra = ui or base[0], extra or base[1]
    if ui not in UIS or extra not in EXTRAS:
        raise ValueError(f'bad ui/extra: {ui!r}/{extra!r}')
    return ui, extra


def matrix(api: int = 36, label: str = 'Q-B bisect') -> list[dict]:
    """matrix.yml `builds` elements: one APK per variant, distinct package. Everything else (requirements
    incl. the materialyoucolor pin, p4a develop, ndk 29, arm64) comes from stub_kivymd/spec_overrides.txt."""
    out = []
    for n, (ui, ex) in enumerate(variants(), 1):
        title = f'Bisect {n} {name(ui, ex)}'
        out.append({
            'name': f'bisect{n}',
            'label': f'{label} {n} {name(ui, ex)}',
            'app': 'stub_kivymd',
            'app_config': {'variant': n},
            'extra': f'package.name=bisect{n};title={title};android.api={api}',
        })
    return out


if __name__ == '__main__':
    print(json.dumps(matrix(*[int(a) for a in sys.argv[1:2]]), separators=(',', ':')))
