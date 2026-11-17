"""KivyMD-FREE helpers shared by showcase.py (the 3-screen inspect app) and bisect_app.py (Q-B ladder).

Nothing here imports kivymd (importing kivymd creates the Window and loads its fonts / theme, which the
plain-Kivy bisect variants must not do). Importing this module patches kivy.uix.screenmanager.Fbo with
CountingFbo, so Fbos made by Kivy shader transitions are counted.

Config (generic, all optional), later sources win:
  1. DEFAULTS below
  2. app_config.json next to this file (inspect.yml / build.yml `app_config` input bakes it)
  3. env vars STUB_<KEY> for any DEFAULTS key (STUB_SHADOWS=0, STUB_VARIANT=3, STUB_AUTOTEST=3)
"""
import json
import os
import sys

from kivy.factory import Factory
from kivy.graphics import Fbo, InstructionGroup
from kivy.graphics.boxshadow import BoxShadow
from kivy.uix import screenmanager

DEFAULTS = {'shadows': True, 'transition': 'Slide', 'count': True, 'insets': False, 'autotest': 0,
            'autotest_touch': False, 'variant': 0, 'ui': '', 'extra': '', 'switches': 20}
FALSE = {'0', 'false', 'False', 'off', 'no', ''}


def coerce(value, default):
    """Convert a config / env value to the type of its default."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else str(value) not in FALSE
    if isinstance(default, int):
        return int(value)
    return str(value)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_config.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            cfg.update(json.load(f))
    for key in DEFAULTS:
        env = os.environ.get('STUB_' + key.upper())
        if env is not None:
            cfg[key] = env
    return {k: coerce(v, DEFAULTS[k]) if k in DEFAULTS else v for k, v in cfg.items()}


class NoShadow(InstructionGroup):
    """Stand-in for BoxShadow: accepts its kv properties, draws nothing, makes no Fbo."""

    def __init__(self, **kwargs):
        super().__init__()
        self.pos = (0, 0)
        self.size = (0, 0)
        self.offset = (0, 0)
        self.spread_radius = (0, 0)
        self.blur_radius = 0
        self.border_radius = (0, 0, 0, 0)
        self.inset = False
        for key, value in kwargs.items():
            setattr(self, key, value)


def disable_shadows() -> None:
    # The <CommonElevationBehavior> kv rule (kivymd/uix/behaviors/elevation.py) names `BoxShadow`
    # in canvas.before; kv resolves canvas instruction names via Factory.get() at each widget's
    # build, so swapping the Factory entry covers every elevated widget built afterwards,
    # including the ones KivyMD builds internally.
    Factory.unregister('BoxShadow')
    Factory.register('BoxShadow', cls=NoShadow)


class CountingFbo(Fbo):
    """kivy.uix.screenmanager.Fbo replacement: counts Fbos made by screen transitions."""
    created = 0

    def __init__(self, *args, **kwargs):
        CountingFbo.created += 1
        super().__init__(*args, **kwargs)


screenmanager.Fbo = CountingFbo  # module global used by ShaderTransition.add_screen


def walk_instructions(group):
    for child in getattr(group, 'children', None) or []:
        yield child
        yield from walk_instructions(child)


def count_tree(widget) -> dict:
    # `elevated` only when kivymd is already imported: never import it from here
    elev = sys.modules.get('kivymd.uix.behaviors.elevation')
    elev_cls = getattr(elev, 'CommonElevationBehavior', None)
    n = {'boxshadow': 0, 'fbo_boxshadow': 0, 'elevated': 0, 'fbo': 0}
    seen = set()  # a child widget's canvas is also nested inside its parent's canvas
    for w in widget.walk(restrict=True):
        if elev_cls is not None and isinstance(w, elev_cls):
            n['elevated'] += 1
        canvas = w.canvas
        for group in (canvas.before, canvas, canvas.after):
            for ins in walk_instructions(group):
                if id(ins) in seen:
                    continue
                seen.add(id(ins))
                if isinstance(ins, Fbo):
                    n['fbo'] += 1
                if isinstance(ins, BoxShadow):
                    n['boxshadow'] += 1
                    n['fbo_boxshadow'] += sum(isinstance(c, Fbo) for c in ins.children)
    return n


def count_line(screen_name: str, widget) -> str:
    """`fbo` = every Fbo instruction in the tree (BoxShadow's own included; raw = fbo - fbo_boxshadow)."""
    n = count_tree(widget)
    return (f'STUB count screen={screen_name} boxshadow={n["boxshadow"]} '
            f'fbo_boxshadow={n["fbo_boxshadow"]} fbo_transition={CountingFbo.created} '
            f'elevated={n["elevated"]} fbo={n["fbo"]}')


def gl_line() -> None:
    try:
        from kivy.graphics import opengl as gl
        vals = []
        for key, enum in (('vendor', gl.GL_VENDOR), ('renderer', gl.GL_RENDERER), ('version', gl.GL_VERSION)):
            raw = gl.glGetString(enum)
            vals.append(f'{key}={raw.decode(errors="replace") if isinstance(raw, bytes) else raw}')
        print('STUB gl', ' '.join(vals))
    except Exception as e:  # noqa: BLE001 - diagnostics only
        print('STUB gl error', repr(e))


def read_insets():
    """(top, bottom, left, right) insets in px = system bars + display cutout (max per side), or None
    off Android / before attach. Also prints `STUB insets parts bars=t,b,l,r cutout=t,b,l,r`."""
    try:
        from jnius import autoclass
    except Exception:  # noqa: BLE001 - desktop
        return None
    try:
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        ins = activity.getWindow().getDecorView().getRootWindowInsets()
        if ins is None:
            return None
        sdk = autoclass('android.os.Build$VERSION').SDK_INT
        if sdk >= 30:
            types = autoclass('android.view.WindowInsets$Type')
            bars_i = ins.getInsets(types.systemBars())
            cut_i = ins.getInsets(types.displayCutout())
            both = ins.getInsets(types.systemBars() | types.displayCutout())  # Type ints OR together
            bars = (bars_i.top, bars_i.bottom, bars_i.left, bars_i.right)
            cutout = (cut_i.top, cut_i.bottom, cut_i.left, cut_i.right)
            total = (both.top, both.bottom, both.left, both.right)
        else:
            bars = (ins.getSystemWindowInsetTop(), ins.getSystemWindowInsetBottom(),
                    ins.getSystemWindowInsetLeft(), ins.getSystemWindowInsetRight())
            dc = ins.getDisplayCutout() if sdk >= 28 else None  # API 28+; None = no cutout
            cutout = ((dc.getSafeInsetTop(), dc.getSafeInsetBottom(),
                       dc.getSafeInsetLeft(), dc.getSafeInsetRight()) if dc is not None else (0, 0, 0, 0))
            total = tuple(max(a, b) for a, b in zip(bars, cutout))
        print(f'STUB insets parts bars={",".join(map(str, bars))} cutout={",".join(map(str, cutout))}')
        return total
    except Exception as e:  # noqa: BLE001 - diagnostics only
        print('STUB insets error', repr(e))
        return None
