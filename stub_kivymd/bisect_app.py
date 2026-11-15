"""Q-B hardware bisection ladder: ONE generator app, the variant picks (ui, extra) by ladder.py's rule.

Screen 1: "Bisect N <name>", a big live counter, the variant's cards and a big START button.
Screen 2: the same counter + the same cards. Cards = 3 kit cards (+ one raw Fbo view when
extra = fbo), so BOTH screens carry the variant's factor. One tap = `switches` (default 20)
automatic switches screen 1 <-> screen 2, each after the transition's duration + 0.3 s, then
"DONE (variant N, 20/20)". The counter `switch k/20` lets a crash be placed by number.

Stress, the same in every variant (so the ladder stays one factor at a time). HYPOTHESIS under test:
the crash being chased (~110 ms into a switch to a screen shown for the first time) is the ARRIVING
screen's Fbos being created and first rendered. So before EVERY switch:
- REBUILD: the ARRIVING screen's cards (+ Fbo view) are thrown away and built fresh, just before the
  transition starts (new Fbos / BoxShadows / MDCards each time);
- NUDGE: during the transition, every frame until on_complete, each Fbo OWNER on the arriving screen
  is nudged once: a widget with nudge() runs it (FboView: moves its disc + ask_update on its Fbo),
  a BoxShadow gets a +-0.01 blur_radius change (re-sets its Fbo's uniforms; assumed, not measured,
  to re-render it), any other bare Fbo gets ask_update(). The Fbo inside a BoxShadow / an owner
  widget is not nudged a second time. A no-op where nothing owns an Fbo (variants 1, 4).

A kit = the ui's manager / screen / transition / card classes; everything else (layout, text,
START / DONE, the switch loop, the printed lines) is shared, so variants differ ONLY by the ladder
factors. START / status / title are plain Kivy Button / Label in every variant (no GL relevance).
ui = kivy never imports kivymd (the kivymd kit imports it inside its function).

Prints (logcat tag `python`): STUB config / bisect variant / transition / gl / count lines,
per switch `STUB bisect variant=N switch=k screen=<arriving> created_widgets= created_boxshadow=
created_fbo=` (made by that switch's rebuild of the arriving screen) and `STUB bisect variant=N switch=k frames= nudged=`, `STUB bisect done ... kivymd_loaded=<bool>` at the end.
Config keys (stubkit.py): variant, ui, extra, switches, count, autotest (> 0 = tap START by itself
after 1.5 s and stop the app 1 s after DONE: desktop / emulator checks).
"""
import json
import sys

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import ClearBuffers, ClearColor, Color, Ellipse, Fbo, Rectangle
from kivy.graphics.boxshadow import BoxShadow
from kivy.metrics import dp
from kivy.uix import screenmanager
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget

import ladder
from stubkit import count_line, count_tree, disable_shadows, gl_line, walk_instructions

N_CARDS = 3


class FboView(Widget):
    """A raw Kivy Fbo: draws a disc into an offscreen texture and shows that texture.
    Moves (pos / size) and nudge() (every transition frame) move the disc and re-render the Fbo."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fbo = Fbo(size=(256, 256))
        with self.fbo:
            ClearColor(0.1, 0.1, 0.35, 1)
            ClearBuffers()
            Color(1, 0.6, 0, 1)
            self.disc = Ellipse(pos=(28, 28), size=(200, 200))
        self.canvas.add(self.fbo)
        with self.canvas:
            Color(1, 1, 1, 1)
            self.rect = Rectangle(texture=self.fbo.texture)
        self.bind(pos=self.redraw, size=self.redraw)

    def redraw(self, *_, frame=0):
        self.rect.pos, self.rect.size = self.pos, self.size
        self.disc.pos = (8 + (self.x + 4 * frame) % 40, 28)
        self.fbo.ask_update()

    def nudge(self, frame: int) -> None:
        self.redraw(frame=frame)


class ShadowButton(Button):
    """A plain Button with a Kivy BoxShadow under it (the instruction KivyMD elevation uses)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0, 0, 0, 0.6)
            self.shadow = BoxShadow(pos=self.pos, size=self.size, offset=(0, -dp(4)),
                                    blur_radius=dp(16), border_radius=(dp(8),) * 4)
        self.bind(pos=self.place, size=self.place)

    def place(self, *_):
        self.shadow.pos, self.shadow.size = self.pos, self.size


def kivy_kit(shadow: bool) -> dict:
    card_cls = ShadowButton if shadow else Button
    return {'app': App, 'manager': screenmanager.ScreenManager, 'screen': screenmanager.Screen,
            'transition': screenmanager.SlideTransition,
            'card': lambda i: card_cls(text=f'card {i}', font_size=dp(22))}


def kivymd_kit(shadow: bool) -> dict:
    from kivymd.app import MDApp
    from kivymd.uix.card import MDCard
    from kivymd.uix.label import MDLabel
    from kivymd.uix.screen import MDScreen
    from kivymd.uix.screenmanager import MDScreenManager
    from kivymd.uix.transition import MDSharedAxisTransition

    if not shadow:
        disable_shadows()  # before any elevated widget is built (see stubkit.disable_shadows)

    def card(i):
        c = MDCard(style='elevated', padding=dp(12))
        c.add_widget(MDLabel(text=f'card {i}', halign='center'))
        return c

    return {'app': MDApp, 'manager': MDScreenManager, 'transition': MDSharedAxisTransition,
            'screen': lambda **kw: MDScreen(md_bg_color=(0.08, 0.08, 0.1, 1), **kw), 'card': card}


KITS = {'kivy': kivy_kit, 'kivymd': kivymd_kit}


class BisectMixin:
    def __init__(self, cfg: dict, n: int, ui: str, extra: str, kit: dict, **kwargs):
        super().__init__(**kwargs)
        self.cfg, self.n, self.ui, self.extra, self.kit = cfg, n, ui, extra, kit
        self.total = cfg['switches']
        self.k = None  # None = not started
        self.nudge_ev = None
        self.frames = self.nudged = 0
        self.label = f'Bisect {n} {ladder.name(ui, extra)}'

    def build(self):
        self.title = self.label
        if self.ui == 'kivymd':
            self.theme_cls.theme_style = 'Dark'
        self.sm = self.kit['manager']()
        s1 = self.kit['screen'](name='s1')
        box = BoxLayout(orientation='vertical', padding=dp(24), spacing=dp(24))
        box.add_widget(Label(text=self.label.replace(' ', '\n', 2), font_size=dp(26), halign='center'))
        self.status = Label(text=f'tap START: {self.total} screen switches', font_size=dp(34))
        box.add_widget(self.status)
        self.start_btn = Button(text='START', font_size=dp(48), size_hint_y=1.4)
        self.start_btn.bind(on_release=self.start)
        s2 = self.kit['screen'](name='s2')
        box2 = BoxLayout(orientation='vertical', padding=dp(32), spacing=dp(32))
        self.counter2 = Label(text='screen 2', font_size=dp(34), size_hint_y=0.6)
        box2.add_widget(self.counter2)
        # one slot per screen for the variant's content; START stays at the bottom of screen 1
        self.slots = {'s1': BoxLayout(size_hint_y=2), 's2': BoxLayout(size_hint_y=N_CARDS + 1)}
        self.content = {'s1': None, 's2': None}
        box.add_widget(self.slots['s1'])
        box.add_widget(self.start_btn)
        box2.add_widget(self.slots['s2'])
        for name in self.slots:
            self.rebuild(name)
        s1.add_widget(box)
        s2.add_widget(box2)
        self.sm.add_widget(s1)
        self.sm.add_widget(s2)
        self.target = 's1'
        # MDScreenManager.__init__ schedules check_transition for the next frame: set ours after it
        Clock.schedule_once(lambda dt: Clock.schedule_once(self.after_first_frame), 0)
        return self.sm

    def make_content(self):
        """The variant's content, built fresh: the cards (+ the Fbo view). Everything here is rebuilt."""
        content = BoxLayout(orientation='vertical', spacing=dp(16))
        for i in range(1, N_CARDS + 1):
            content.add_widget(self.kit['card'](i))
        if self.extra == 'fbo':
            content.add_widget(FboView())
        return content

    def rebuild(self, name: str) -> dict:
        """Replace screen `name`'s content with a fresh one; returns what was created."""
        slot = self.slots[name]
        if self.content[name] is not None:
            slot.remove_widget(self.content[name])
        self.content[name] = self.make_content()
        slot.add_widget(self.content[name])
        n = count_tree(self.content[name])
        n['widgets'] = sum(1 for _ in self.content[name].walk(restrict=True))
        return n

    def nudge(self, dt) -> None:
        """One transition frame: nudge each Fbo owner on the arriving screen exactly once."""
        self.frames += 1
        widgets = list(self.content[self.target].walk(restrict=True))
        seen = set()  # instructions already handled; a child's canvas is nested in its parent's too
        for w in widgets:  # pass 1: widgets that re-render their own Fbo(s)
            if hasattr(w, 'nudge'):
                w.nudge(self.frames)
                self.nudged += 1
                seen.update(id(i) for c in (w.canvas.before, w.canvas, w.canvas.after)
                            for i in walk_instructions(c))
        for w in widgets:  # pass 2: BoxShadows (their own Fbo included), then any other bare Fbo
            for group in (w.canvas.before, w.canvas, w.canvas.after):
                for ins in walk_instructions(group):
                    if id(ins) in seen:
                        continue
                    seen.add(id(ins))
                    if isinstance(ins, BoxShadow):
                        ins.blur_radius = ins.blur_radius + (0.01 if self.frames % 2 else -0.01)
                        seen.update(id(i) for i in walk_instructions(ins))
                        self.nudged += 1
                    elif isinstance(ins, Fbo):
                        ins.ask_update()
                        self.nudged += 1

    def stop_nudge(self, *_) -> None:
        if self.nudge_ev is not None:
            self.nudge_ev.cancel()
            self.nudge_ev = None
            print(f'STUB bisect variant={self.n} switch={self.k} frames={self.frames} nudged={self.nudged}')

    def on_start(self):
        gl_line()

    def after_first_frame(self, dt) -> None:
        self.sm.transition = self.kit['transition']()
        print('STUB transition', type(self.sm.transition).__name__)
        self.sm.transition.bind(on_complete=self.stop_nudge)
        for screen in self.sm.screens:
            screen.bind(on_enter=lambda s: self.count())
        self.count()
        if self.cfg['autotest'] > 0:
            Clock.schedule_once(self.start, 1.5)

    def count(self) -> None:
        if self.cfg['count'] and self.sm.current_screen is not None:
            print(count_line(self.sm.current, self.sm.current_screen))

    def start(self, *_):
        if self.k is not None:
            return
        self.k = 0
        self.start_btn.disabled = True
        Clock.schedule_once(self.step, 0)

    def step(self, dt) -> None:
        self.stop_nudge()
        if self.k >= self.total:
            if self.sm.current != 's1':  # odd `switches`: one extra, uncounted return to screen 1
                self.sm.current = 's1'
            self.finish()
            return
        self.k += 1
        self.target = 's2' if self.sm.current == 's1' else 's1'
        self.status.text = self.counter2.text = f'switch {self.k}/{self.total}'
        n = self.rebuild(self.target)  # fresh ARRIVING content, created just before the transition
        print(f'STUB bisect variant={self.n} switch={self.k} screen={self.target} created_widgets={n["widgets"]} '
              f'created_boxshadow={n["boxshadow"]} created_fbo={n["fbo"]}')
        self.frames = self.nudged = 0
        self.sm.current = self.target
        self.nudge_ev = Clock.schedule_interval(self.nudge, 0)  # every frame until on_complete
        Clock.schedule_once(self.step, self.sm.transition.duration + 0.3)

    def finish(self) -> None:
        done = f'DONE (variant {self.n}, {self.k}/{self.total})'
        self.status.text = done
        self.status.font_size = dp(34)
        self.start_btn.text = 'DONE'
        print(f'STUB bisect done variant={self.n} switches={self.k}/{self.total} '
              f'kivymd_loaded={"kivymd" in sys.modules}')
        if self.cfg['autotest'] > 0:
            Clock.schedule_once(lambda dt: self.stop(), 1.0)


def run(cfg: dict) -> None:
    n = cfg['variant']
    ui, extra = ladder.resolve(n, cfg['ui'], cfg['extra'])
    print('STUB config', json.dumps(cfg, sort_keys=True))
    print(f'STUB bisect variant={n} ui={ui} extra={extra} name={ladder.name(ui, extra)!r} switches={cfg["switches"]}')
    kit = KITS[ui](extra == 'shadow')
    app_cls = type('BisectApp', (BisectMixin, kit['app']), {})
    app_cls(cfg, n, ui, extra, kit).run()
