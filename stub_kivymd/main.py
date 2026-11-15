"""KivyMD 2.x test app for inspect.yml: 3 screens, top app bar, elevated cards, buttons.

Config (generic, all optional), later sources win:
  1. DEFAULTS below
  2. app_config.json next to this file (inspect.yml / build.yml `app_config` input bakes it)
  3. env vars STUB_SHADOWS=0|1, STUB_TRANSITION=<name> (desktop runs)
transition = a Kivy screenmanager name (Slide, Fade, No, Swap, ...) or a KivyMD one
(MDSlide, MDFadeSlide, MDSharedAxis, ...). shadows = False zeroes every elevation shadow
(the BoxShadow instruction of CommonElevationBehavior), for shadow on/off comparisons.

Every config + screen change is printed as a `STUB ...` line, so it lands in logcat.
Tapping the center of the screen (the big card) goes to the next screen.
"""
import json
import os

from kivy.lang import Builder
from kivy.uix import screenmanager
from kivymd.app import MDApp
from kivymd.uix import transition as md_transition
from kivymd.uix.behaviors.elevation import CommonElevationBehavior

DEFAULTS = {'shadows': True, 'transition': 'Slide'}
SCREENS = ['home', 'second', 'third']


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_config.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            cfg.update(json.load(f))
    if 'STUB_SHADOWS' in os.environ:
        cfg['shadows'] = os.environ['STUB_SHADOWS'] not in {'0', 'false', 'False', 'off'}
    if 'STUB_TRANSITION' in os.environ:
        cfg['transition'] = os.environ['STUB_TRANSITION']
    if isinstance(cfg['shadows'], str):
        cfg['shadows'] = cfg['shadows'] not in {'0', 'false', 'False', 'off'}
    return cfg


def make_transition(name: str):
    for module in (screenmanager, md_transition):
        cls = getattr(module, f'{name}Transition', None)
        if cls is not None:
            return cls()
    raise ValueError(f'unknown transition {name!r}')


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
            # class-level defaults: every elevated widget built after this has no shadow
            CommonElevationBehavior.shadow_color = (0, 0, 0, 0)
        root = Builder.load_string(KV)
        root.transition = make_transition(self.cfg['transition'])
        if not self.cfg['shadows']:
            for w in root.walk(restrict=False):
                if isinstance(w, CommonElevationBehavior):
                    w.shadow_color = (0, 0, 0, 0)
        print('STUB screen', root.current)
        return root

    def go(self, name: str) -> None:
        self.root.current = name
        print('STUB screen', name)


if __name__ == '__main__':
    StubKivyMDApp().run()
