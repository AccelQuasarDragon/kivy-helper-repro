"""KivyMD 2.x test app for inspect.yml: 3 screens, top app bar, elevated cards, buttons.

Config (generic, all optional), later sources win:
  1. DEFAULTS below
  2. app_config.json next to this file (inspect.yml / build.yml `app_config` input bakes it)
  3. env vars STUB_<KEY> for any DEFAULTS key (STUB_SHADOWS=0, STUB_TRANSITION=Fade, STUB_AUTOTEST=3)
Keys:
  transition  a Kivy screenmanager name (Slide, Fade, No, Swap, ...) or a KivyMD one (MDSlide,
              MDFadeSlide, MDSharedAxis, ...). Applied one frame after build: MDScreenManager
              replaces a non-MD transition set earlier with MDSharedAxisTransition.
  shadows     False = Factory's BoxShadow is replaced by a no-op group BEFORE any KV builds an
              elevated widget, so no BoxShadow (and no BoxShadow Fbo) exists at all.
  count       print a `STUB count ...` line after start and after each screen switch.
  insets      Android: pad the root by the system bar insets (pyjnius); desktop: no-op.
  autotest    N > 0 = switch screens N times automatically (1.5 s apart), then stop the app.

Every config, screen change and measurement is printed as a `STUB ...` line, so it lands in logcat.
Tapping the center of the screen (the big card) goes to the next screen.
"""
import json
import os

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.graphics import Fbo, InstructionGroup
from kivy.graphics.boxshadow import BoxShadow
from kivy.lang import Builder
from kivy.uix import screenmanager
from kivy.uix.boxlayout import BoxLayout
from kivymd.app import MDApp
from kivymd.uix import transition as md_transition
from kivymd.uix.behaviors.elevation import CommonElevationBehavior

DEFAULTS = {'shadows': True, 'transition': 'Slide', 'count': True, 'insets': False, 'autotest': 0}
SCREENS = ['home', 'second', 'third']
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


def make_transition(name: str):
    for module in (screenmanager, md_transition):
        cls = getattr(module, f'{name}Transition', None)
        if cls is not None:
            return cls()
    raise ValueError(f'unknown transition {name!r}')


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
    n = {'boxshadow': 0, 'fbo_boxshadow': 0, 'elevated': 0}
    seen = set()  # a child widget's canvas is also nested inside its parent's canvas
    for w in widget.walk(restrict=True):
        if isinstance(w, CommonElevationBehavior):
            n['elevated'] += 1
        canvas = w.canvas
        for group in (canvas.before, canvas, canvas.after):
            for ins in walk_instructions(group):
                if id(ins) in seen:
                    continue
                seen.add(id(ins))
                if isinstance(ins, BoxShadow):
                    n['boxshadow'] += 1
                    n['fbo_boxshadow'] += sum(isinstance(c, Fbo) for c in ins.children)
    return n


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
    """(top, bottom, left, right) system bar insets in px, or None off Android / before attach."""
    try:
        from jnius import autoclass
    except Exception:  # noqa: BLE001 - desktop
        return None
    try:
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        ins = activity.getWindow().getDecorView().getRootWindowInsets()
        if ins is None:
            return None
        if autoclass('android.os.Build$VERSION').SDK_INT >= 30:
            bars = ins.getInsets(autoclass('android.view.WindowInsets$Type').systemBars())
            return bars.top, bars.bottom, bars.left, bars.right
        return (ins.getSystemWindowInsetTop(), ins.getSystemWindowInsetBottom(),
                ins.getSystemWindowInsetLeft(), ins.getSystemWindowInsetRight())
    except Exception as e:  # noqa: BLE001 - diagnostics only
        print('STUB insets error', repr(e))
        return None


KV = '''
<StubScreen@MDScreen>:
    md_bg_color: self.theme_cls.backgroundColor
    title: ''
    body: ''
    next_name: ''
    MDBoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            type: 'small'
            MDTopAppBarLeadingButtonContainer:
                MDActionTopAppBarButton:
                    icon: 'menu'
            MDTopAppBarTitle:
                text: root.title
            MDTopAppBarTrailingButtonContainer:
                MDActionTopAppBarButton:
                    icon: 'account-circle-outline'
        MDAnchorLayout:
            MDCard:
                style: 'elevated'
                size_hint: .85, .6
                padding: '16dp'
                spacing: '16dp'
                orientation: 'vertical'
                on_release: app.go(root.next_name)
                MDLabel:
                    text: root.body
                    font_style: 'Headline'
                    role: 'small'
                    halign: 'center'
                MDCard:
                    style: 'elevated'
                    size_hint_y: None
                    height: '96dp'
                    padding: '12dp'
                    MDLabel:
                        text: 'nested elevated card (shadow test)'
                        halign: 'center'
                MDAnchorLayout:
                    size_hint_y: None
                    height: '64dp'
                    MDButton:
                        style: 'elevated'
                        on_release: app.go(root.next_name)
                        MDButtonText:
                            text: 'Next: ' + root.next_name

MDScreenManager:
    StubScreen:
        name: 'home'
        title: 'Home'
        body: 'Screen 1 of 3: tap the card'
        next_name: 'second'
    StubScreen:
        name: 'second'
        title: 'Second'
        body: 'Screen 2 of 3'
        next_name: 'third'
    StubScreen:
        name: 'third'
        title: 'Third'
        body: 'Screen 3 of 3'
        next_name: 'home'
'''


class StubKivyMDApp(MDApp):
    def build(self):
        self.cfg = load_config()
        print('STUB config', json.dumps(self.cfg, sort_keys=True))
        if not self.cfg['shadows']:
            disable_shadows()
        self.sm = Builder.load_string(KV)
        # the root box exists so `insets` can pad it; padding 0 = the same look as the bare manager
        root = BoxLayout()
        root.add_widget(self.sm)
        print('STUB screen', self.sm.current)
        # MDScreenManager.__init__ scheduled check_transition for the next frame: apply ours after it
        Clock.schedule_once(lambda dt: Clock.schedule_once(self.after_first_frame), 0)
        return root

    def on_start(self):
        gl_line()

    def after_first_frame(self, dt) -> None:
        self.sm.transition = make_transition(self.cfg['transition'])
        print('STUB transition', type(self.sm.transition).__name__)
        for screen in self.sm.screens:
            screen.bind(on_enter=lambda s: self.count())
        self.count()
        self.apply_insets()
        if self.cfg['insets']:
            Clock.schedule_once(lambda dt: self.apply_insets(), 1.0)  # again once fully attached
        if self.cfg['autotest'] > 0:
            self.autotest_left = self.cfg['autotest']
            Clock.schedule_once(self.autotest_step, 1.5)

    def count(self) -> None:
        if not self.cfg['count'] or self.sm.current_screen is None:
            return
        n = count_tree(self.sm.current_screen)
        print(f'STUB count screen={self.sm.current} boxshadow={n["boxshadow"]} '
              f'fbo_boxshadow={n["fbo_boxshadow"]} fbo_transition={CountingFbo.created} '
              f'elevated={n["elevated"]}')

    def apply_insets(self) -> None:
        ins = read_insets() if self.cfg['insets'] else None
        applied = ins is not None
        top, bottom, left, right = ins or (0, 0, 0, 0)
        if applied:
            self.root.padding = [left, top, right, bottom]  # Kivy padding = left, top, right, bottom
        print(f'STUB insets top={top} bottom={bottom} left={left} right={right} applied={applied}')

    def autotest_step(self, dt) -> None:
        if self.autotest_left <= 0:
            print('STUB autotest done')
            self.stop()
            return
        self.autotest_left -= 1
        self.go(self.sm.get_screen(self.sm.current).next_name)
        Clock.schedule_once(self.autotest_step, 1.5)

    def go(self, name: str) -> None:
        self.sm.current = name
        print('STUB screen', name)


if __name__ == '__main__':
    StubKivyMDApp().run()
