# /// script
# requires-python = '>=3.10,<3.14'
# dependencies = [
#   'kivy==2.3.1',
#   'kivymd @ https://github.com/kivymd/KivyMD/archive/a00c10c385064afb3a46b3a10d1d2c0c6505dc48.zip',
# ]
# ///
"""Desktop runtime check of the controlP ripple toggles in patches/controlp/bisect_toggles.diff (needs a display).

  uv run --script tools/ripple_runtime_check.py        # all modes, one child process each; exit 0 = all pass

Opens a small Kivy window for a moment per mode. Each child: extracts _bisect.py from the diff into a temp dir
(with an app_config.json for the mode), puts a spy on ripple_behavior.Fbo (records whether `fs` was given at
creation and whether shader.fs changed afterwards), imports _bisect (its ripple patches install; the controlP
part warns and is skipped), builds the stock widgets controlP taps (MDListItem with avatar, MDIconButton, MDButton),
runs one ripple per widget (the method a tap calls 1/30 s after touch down), lets it animate 0.3 s, then
anim_complete. Checks per mode: which class provides the patched method (MRO), the instructions the ripple
adds, that anim_complete removes all of them, and the Fbo shader history. Not run in CI (Kivy + a display)."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
DIFF = os.path.join(ROOT, 'patches', 'controlp', 'bisect_toggles.diff')
MODES = {'shipped': {}, 'fbo_fs': {'ripple_fbo_fs': 'create'}, 'stencil': {'ripple_stencil': False},
         'list': {'list_ripple': False}}
GROUP = 'm3_ripple_behavior'
RIPPLE_MARK = 'in_turbulencePhase'  # a uniform only ripple.glsl declares


def bisect_source() -> str:
    text = open(DIFF, encoding='utf-8').read()
    hunk = text.split('+++ b/src/controlp/_bisect.py\n', 1)[1].split('\ndiff --git', 1)[0]
    return ''.join(line[1:] + '\n' for line in hunk.splitlines()[1:] if line.startswith('+'))


def child(mode: str) -> None:
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, 'controlp'))
    open(os.path.join(tmp, 'controlp', '__init__.py'), 'w').close()
    open(os.path.join(tmp, 'controlp', '_bisect.py'), 'w', encoding='utf-8').write(bisect_source())
    json.dump(MODES[mode], open(os.path.join(tmp, 'app_config.json'), 'w'))
    sys.path.insert(0, tmp)
    os.environ.setdefault('KIVY_NO_ARGS', '1')
    from kivy.config import Config
    Config.set('graphics', 'width', '400')
    Config.set('graphics', 'height', '300')
    import kivymd.uix.behaviors.ripple_behavior as rb

    spies = []

    class SpyFbo(rb.Fbo):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.fs_given = 'fs' in kwargs
            self.fs_at_create = self.shader.fs
            spies.append(self)

    rb.Fbo = SpyFbo
    import controlp._bisect as bis  # noqa: F401 - installs the ripple patches for this mode
    from kivy.clock import Clock
    from kivy.uix.boxlayout import BoxLayout
    from kivymd.app import MDApp
    from kivymd.uix.button import MDButton, MDButtonText, MDIconButton
    from kivymd.uix.list import MDListItem, MDListItemHeadlineText, MDListItemLeadingAvatar

    out = {'mode': mode, 'widgets': {}}

    class Check(MDApp):
        def build(self):
            self.w_avatar = MDListItemLeadingAvatar()
            self.w_item = MDListItem(self.w_avatar, MDListItemHeadlineText(text='row'))
            self.w_icon = MDIconButton(icon='power')
            self.w_button = MDButton(MDButtonText(text='ok'))
            root = BoxLayout(orientation='vertical')
            for w in (self.w_item, self.w_icon, self.w_button):
                root.add_widget(w)
            return root

        def on_start(self):
            Clock.schedule_once(self.tap, 0.5)

        def widgets(self):
            return {'MDListItem': self.w_item, 'MDListItemLeadingAvatar': self.w_avatar,
                    'MDIconButton': self.w_icon, 'MDButton': self.w_button}

        def tap(self, dt):
            for name, w in self.widgets().items():
                cls = type(w)
                rec = {'lay_canvas_instructions': cls.lay_canvas_instructions.__qualname__,
                       'init_fbos': cls.init_fbos.__qualname__,
                       'm3': isinstance(w, rb.M3CommonRipple), 'ripple_effect': w.ripple_effect,
                       'before': len(w.active_canvas.children)}
                w.ripple_pos = [w.width / 2, w.height / 2]
                w._call_ripple_animation_methods(0)
                rec['added'] = [(type(i).__name__, getattr(i, 'group', None))
                                for i in w.active_canvas.children[rec['before']:]]
                out['widgets'][name] = rec
            Clock.schedule_once(self.finish, 0.3)

        def finish(self, dt):
            for name, w in self.widgets().items():
                rec = out['widgets'][name]
                rec['during'] = len(w.active_canvas.children) - rec['before']
                w.anim_complete()
                rec['after'] = len(w.active_canvas.children) - rec['before']
                rec['group_left'] = sum(getattr(i, 'group', None) == GROUP for i in w.active_canvas.children)
            out['fbos'] = [{'fs_given': s.fs_given, 'fs_changed_after_create': s.shader.fs != s.fs_at_create,
                            'ripple_fs': RIPPLE_MARK in (s.shader.fs or '')} for s in spies]
            out['counters'] = dict(bis.RIPPLE)
            print('RESULT ' + json.dumps(out))
            self.stop()

    Check().run()


def verdict(r: dict) -> list:
    """(ok, message) per expectation for one mode's RESULT."""
    mode, ws, fbos = r['mode'], r['widgets'], r['fbos']
    stencil = {'StencilPush', 'StencilUse', 'StencilUnUse', 'StencilPop'}
    res = [(len(fbos) == 4, f'{mode}: 4 ripple Fbos made (one per widget), got {len(fbos)}'),
           (all(f['ripple_fs'] for f in fbos), f'{mode}: every ripple Fbo ends with the ripple shader')]
    lay = 'm3_ripple_no_stencil' if mode == 'stencil' else 'M3CommonRipple.lay_canvas_instructions'
    init = 'm3_init_fbos_fs_at_create' if mode == 'fbo_fs' else 'M3CommonRipple.init_fbos'
    for name, w in ws.items():
        res.append((w['m3'] and w['lay_canvas_instructions'] == lay and w['init_fbos'] == init,
                    f'{mode}: {name} is M3CommonRipple, uses {lay} + {init}'))
        kinds = ['Fbo' if k == 'SpyFbo' else k for k, _ in w['added']]
        grouped = [g for k, g in w['added'] if k != 'BindTexture']  # Kivy adds BindTexture for textured shapes
        if mode == 'list' and name == 'MDListItem':
            res.append((not w['ripple_effect'] and not kinds, f'{mode}: MDListItem ripple_effect False, tap adds nothing'))
            continue
        res.append((w['ripple_effect'] and 'Fbo' in kinds and all(g == GROUP for g in grouped),
                    f'{mode}: {name} tap adds the Fbo + only group {GROUP}: {kinds}'))
        has_stencil = bool(stencil & set(kinds))
        res.append((has_stencil == (mode != 'stencil'), f'{mode}: {name} stencil instructions present = {has_stencil}'))
        res.append((w['after'] == 0 and w['group_left'] == 0, f'{mode}: {name} anim_complete removes all it added'))
    if mode == 'fbo_fs':
        res.append((all(f['fs_given'] and not f['fs_changed_after_create'] for f in fbos),
                    f'{mode}: every ripple Fbo got fs at creation, no shader.fs change after'))
    else:
        res.append((all(not f['fs_given'] and f['fs_changed_after_create'] for f in fbos),
                    f'{mode}: shipped path: Fbo made without fs, shader.fs set after creation (the #8098 pattern)'))
    return res


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == '--child':
        child(sys.argv[2])
        return 0
    ok = True
    for mode in MODES:
        p = subprocess.run([sys.executable, os.path.abspath(__file__), '--child', mode],
                           capture_output=True, text=True, timeout=180)
        lines = [x for x in p.stdout.splitlines() if x.startswith(('RESULT ', 'STUB '))]
        for x in lines:
            if x.startswith('STUB '):
                print(f'[{mode}] {x}')
        res = [x for x in lines if x.startswith('RESULT ')]
        if not res:
            print(f'FAIL {mode}: no RESULT (exit {p.returncode}): {(p.stderr or p.stdout)[-800:]}')
            ok = False
            continue
        for good, msg in verdict(json.loads(res[0][7:])):
            print(('PASS ' if good else 'FAIL ') + msg)
            ok = ok and good
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
