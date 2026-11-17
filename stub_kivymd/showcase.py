"""KivyMD 2.x test app for inspect.yml: 3 screens, top app bar, elevated cards, buttons.

Started by main.py when the config has no bisect `variant` (config: stubkit.py, keys below).
Keys:
  transition  a Kivy screenmanager name (Slide, Fade, No, Swap, ...) or a KivyMD one (MDSlide,
              MDFadeSlide, MDSharedAxis, ...). Applied one frame after build: MDScreenManager
              replaces a non-MD transition set earlier with MDSharedAxisTransition.
  shadows     False = Factory's BoxShadow is replaced by a no-op group BEFORE any KV builds an
              elevated widget, so no BoxShadow (and no BoxShadow Fbo) exists at all.
  count       print a `STUB count ...` line after start and after each screen switch.
  insets      Android: pad the root by the system bar + cutout insets (pyjnius); desktop: no-op. The insets are
              READ and logged always (a number for the overlap); this key only decides the padding.
  autotest    N > 0 = switch screens N times automatically (1.5 s apart), then stop the app.
  autotest_touch  False = autotest switches by code; True = through the REAL input path: the mouse
              moves onto the big card (KivyMD hover) and a touch down/up goes through the EventLoop,
              like a tap on a phone (catches what only a touch imports, e.g. kivymd.uix.list).

Every config, screen change and measurement is printed as a `STUB ...` line, so it lands in logcat.
Tapping the center of the screen (the big card) goes to the next screen.
"""
import json

from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.input.motionevent import MotionEvent
from kivy.lang import Builder
from kivy.uix import screenmanager
from kivy.uix.boxlayout import BoxLayout
from kivymd.app import MDApp
from kivymd.uix import transition as md_transition

from stubkit import count_line, disable_shadows, gl_line, read_insets

SCREENS = ['home', 'second', 'third']


def make_transition(name: str):
    for module in (screenmanager, md_transition):
        cls = getattr(module, f'{name}Transition', None)
        if cls is not None:
            return cls()
    raise ValueError(f'unknown transition {name!r}')


class TapEvent(MotionEvent):
    """A synthetic touch at window coords (x, y), dispatched through the EventLoop like a real one."""

    def __init__(self, x, y):
        win = EventLoop.window
        super().__init__('stubtap', 1, {'x': x / (win.width - 1.0), 'y': y / (win.height - 1.0)},
                         is_touch=True, type_id='touch')

    def depack(self, args):
        self.sx, self.sy = args['x'], args['y']
        super().depack(args)


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
    def __init__(self, cfg: dict, **kwargs):
        super().__init__(**kwargs)
        self.cfg = cfg

    def build(self):
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
        Clock.schedule_once(lambda dt: self.apply_insets(), 1.0)  # again once fully attached
        if self.cfg['autotest'] > 0:
            self.autotest_left = self.cfg['autotest']
            Clock.schedule_once(self.autotest_step, 1.5)

    def count(self) -> None:
        if not self.cfg['count'] or self.sm.current_screen is None:
            return
        print(count_line(self.sm.current, self.sm.current_screen))

    def apply_insets(self) -> None:
        # always READ (the logged numbers measure the overlap even with padding off); PAD only when `insets`
        ins = read_insets()
        top, bottom, left, right = ins if ins is not None else ('n/a',) * 4
        applied = bool(self.cfg['insets']) and ins is not None
        if applied:
            self.root.padding = [left, top, right, bottom]  # Kivy padding = left, top, right, bottom
        print(f'STUB insets top={top} bottom={bottom} left={left} right={right} applied={applied}')

    def autotest_step(self, dt) -> None:
        if self.autotest_left <= 0:
            print('STUB autotest done')
            self.stop()
            return
        self.autotest_left -= 1
        if self.cfg.get('autotest_touch'):
            self.tap_card()
        else:
            self.go(self.sm.get_screen(self.sm.current).next_name)
        Clock.schedule_once(self.autotest_step, 1.5)

    def tap_card(self) -> None:
        """Hover + tap the big card (upper part: the center may be the nested card) via the real input path."""
        from kivy.core.window import Window
        from kivymd.uix.card import MDCard
        card = next(w for w in self.sm.current_screen.walk(restrict=True) if isinstance(w, MDCard))
        x, y = card.to_window(card.center_x, card.y + card.height * 0.85)
        print(f'STUB tap x={int(x)} y={int(y)} screen={self.sm.current}')
        Window.mouse_pos = (x, y)  # KivyMD HoverBehavior binds Window.mouse_pos
        touch = TapEvent(x, y)
        EventLoop._dispatch_input('begin', touch)
        Clock.schedule_once(lambda dt: EventLoop._dispatch_input('end', touch), 0.1)

    def go(self, name: str) -> None:
        self.sm.current = name
        print('STUB screen', name)


def run(cfg: dict) -> None:
    StubKivyMDApp(cfg).run()
