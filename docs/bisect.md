# Q-B hardware bisection kit: 5 test APKs for a phone that crashes

For people and LLMs. Spec: the removed QUEUE.md "Q-B HARDWARE BISECTION KIT" (git history, commit bcdce3c). Code: `stub_kivymd/ladder.py` (the
rule), `stub_kivymd/bisect_app.py` (the app), `.github/workflows/matrix.yml` (one run, 5 APKs).

## Why
A KivyMD app crashes in the GPU driver (native SIGSEGV, nested Fbo draw) about 110 ms into a switch
to a screen shown for the first time (an earlier switch to another screen survived). HYPOTHESIS
under test (not established): the ARRIVING screen's Fbos being created and first rendered trigger it.
Emulators render in software and cannot show a driver crash, so the phone owner runs 5 small APKs.
Each adds one factor; the FIRST one that crashes names the trigger.

## The ladder (one generator)
`ladder.py`: a variant is a point (ui, extra); variants 1..5 = (kivy, kivymd) x (plain, fbo, shadow)
in that order, minus (kivymd, fbo) (kept out to stay at 5; set `ui` / `extra` directly to run it).
BOTH screens hold the variant's content: 3 cards, Kivy `Button`s (ui kivy) or elevated `MDCard`s
(ui kivymd), plus the Fbo view in variant 2. Screen 1 also has START at the bottom. At LAUNCH
neither screen has its cards: launch draws no variant Fbo / BoxShadow (desktop count line at launch:
`boxshadow=0 fbo=0` in all 5). Each screen's cards are first built when it arrives (screen 2 at
switch 1, screen 1 at switch 2).

| # | name (app title `Bisect N <name>`) | package | ladder step | made per switch (desktop) | Fbo owners nudged per frame |
|---|---|---|---|---|---|
| 1 | Kivy plain | org.khr.bisect1 | plain Kivy ScreenManager + SlideTransition | 4 widgets, 0 BoxShadow, 0 Fbo | 0 |
| 2 | Kivy Fbo | org.khr.bisect2 | 1 + one raw Kivy Fbo | 5 widgets, 0 BoxShadow, 1 Fbo | 1 |
| 3 | Kivy BoxShadow | org.khr.bisect3 | 1 + 3 widgets with Kivy BoxShadow | 4 widgets, 3 BoxShadow, 3 Fbo | 3 |
| 4 | KivyMD plain | org.khr.bisect4 | MDScreenManager + MDSharedAxis, elevated cards, shadows OFF | 7 widgets, 0 BoxShadow, 0 Fbo | 0 |
| 5 | KivyMD BoxShadow | org.khr.bisect5 | 4 with stock shadows ON | 7 widgets, 3 BoxShadow, 3 Fbo | 3 |

The same stress in every variant, so the ladder stays one factor at a time:
- REBUILD: just before EVERY switch, the ARRIVING screen's cards (+ Fbo view) are thrown away and
  built fresh, so each of the 20 transitions creates and first-renders new Fbos / BoxShadows /
  MDCards on the arriving screen: 20 tries at the hypothesised moment instead of one. The counts
  are the same on all 20 switches (10 arriving on screen 2, 10 on screen 1).
- NUDGE: during each transition (every frame until the transition's on_complete), each Fbo OWNER on
  the arriving screen is nudged once: the Fbo view moves its disc + `ask_update()` on its Fbo; a
  BoxShadow gets a +-0.01 `blur_radius` change, which re-sets its Fbo's uniforms and is ASSUMED
  (unmeasured, see Untested) to re-render it; a BoxShadow's own Fbo is not nudged a second time.
  Nothing to nudge in variants 1 and 4.

Variants 1-3 never import kivymd (`kivymd_loaded=False` in the done line); all 5 APKs have the same
requirements and differ only by `app_config` + package name / title. Shadows OFF = stubkit's
Factory swap (no BoxShadow, no BoxShadow Fbo at all). START, the counter and the titles are plain
Kivy widgets in every variant.

What the app does: screen 1 shows `Bisect N <name>`, the cards and a big START. One tap = 20 automatic switches
screen 1 <-> screen 2, each after the transition's duration + 0.3 s (Slide 0.7 s, MDSharedAxis
0.5 s); both screens show a big `switch k/20` counter; at the end `DONE (variant N, 20/20)`.
Logcat (tag `python`): `STUB bisect variant=N ui= extra=`, `STUB gl ...` (the GPU line), per switch
`STUB bisect variant=N switch=k screen=s1|s2 created_widgets= created_boxshadow= created_fbo=` then
`STUB bisect variant=N switch=k frames= nudged=`, a `STUB count ...` line on each arrival, and
`STUB bisect done variant=N switches=20/20 kivymd_loaded=<bool>`.

## 1. Build: ONE matrix run (Actions -> "build matrix" -> Run workflow)
label `Q-B bisect kit`, builds = this JSON (regenerate: `uv run --no-project stub_kivymd/ladder.py`):

```json
[{"name":"bisect1","label":"Q-B bisect 1 Kivy plain","app":"stub_kivymd","app_config":{"variant":1},"extra":"package.name=bisect1;title=Bisect 1 Kivy plain;android.api=36","add_archs":"x86_64"},{"name":"bisect2","label":"Q-B bisect 2 Kivy Fbo","app":"stub_kivymd","app_config":{"variant":2},"extra":"package.name=bisect2;title=Bisect 2 Kivy Fbo;android.api=36","add_archs":"x86_64"},{"name":"bisect3","label":"Q-B bisect 3 Kivy BoxShadow","app":"stub_kivymd","app_config":{"variant":3},"extra":"package.name=bisect3;title=Bisect 3 Kivy BoxShadow;android.api=36","add_archs":"x86_64"},{"name":"bisect4","label":"Q-B bisect 4 KivyMD plain","app":"stub_kivymd","app_config":{"variant":4},"extra":"package.name=bisect4;title=Bisect 4 KivyMD plain;android.api=36","add_archs":"x86_64"},{"name":"bisect5","label":"Q-B bisect 5 KivyMD BoxShadow","app":"stub_kivymd","app_config":{"variant":5},"extra":"package.name=bisect5;title=Bisect 5 KivyMD BoxShadow;android.api=36","add_archs":"x86_64"}]
```

Everything else comes from `stub_kivymd/spec_overrides.txt`: p4a develop, android.ndk 29, archs
arm64-v8a, Kivy 2.3.2, KivyMD master, `materialyoucolor==3.0.4` (p4a develop's recipe ships 2.0.10,
which lacks `dynamiccolor.color_spec` that KivyMD master imports; `name==ver` makes p4a fetch the
v3.0.4 release tarball), `materialshapes` + `pycairo` (the first touch imports them via
kivymd.uix.list -> fitimage; since 2026-11-15 push 2). `extra` raises android.api to 36 (the reporter's). `"add_archs":"x86_64"`
makes each APK FAT (arm64-v8a + x86_64): ONE file per variant serves both the x86_64 emulator gate
(section 2, no rebuild) and the arm64 phone (Android picks the arm64 lib on the device). Cache `off`
(cold, the only evidence). Artifacts `build-<run_number>-bisect1..5-a<attempt>` hold the debug APKs;
the `facts` job prints package / targetSdk / ABIs / sha256 of all 5 (check: 5 distinct packages,
ABIs `arm64-v8a x86_64`).

## 2. GATE: emulator smoke test of all 5 before anything is sent (Q-B acceptance)
inspect.yml, one run per variant on the matrix run's OWN APK (no rebuild): `artifact_run` = the
matrix run's ID (the number in its URL `.../actions/runs/<id>`), `artifact_name` =
`build-<run_number>-bisectN-a<attempt>` (`<run_number>` = the matrix run's number `#n`, not its ID;
highest attempt, as in section 3), app / repo / archs / extra / app_config empty (no build), taps
`540,2060,30` (START = the bottom part of screen 1; measured on desktop at 1080x2400, density
2.625 = pixel_6: x 63..1017, y 1796..2337, center 540,2067), launch_wait 30, label e.g.
`Q-B gate N`. The run fails early if the artifact has no x86_64 lib (then the matrix lacked
`add_archs`).
PASS for a variant = the screenshot after the tap shows `DONE (variant N, 20/20)`, logcat has 20
`created_` lines and 20 `frames=` lines, `app pid at end` is set, no Python traceback. All 5 must pass
before the APKs go out; a failure here is our bug, not the phone's. Do not use `autotest` here (it
stops the app after DONE, which reads like a crash). The software emulator CANNOT clear a GPU-driver
crash: the gate only proves the app itself runs. The phone gets the SAME fat APK the gate ran (same
sha256 in both summaries); on the phone Android uses its arm64 lib, so the gate checks the Python
side and the packaging, not the arm64 native code.

## 3. Send: what the helper does
1. Open the matrix run on GitHub (logged in) and download, for each of bisect1..5, the artifact
   `build-<run>-bisectN-a<n>` with the HIGHEST `-a<n>` (after a re-run, `-a1` holds only the failed
   attempt's log; same rule as the facts table) (zip files), unzip each, and take out the one `.apk` in each (fat: `bisect1-0.1-arm64-v8a_x86_64-debug.apk` ...,
   name as buildozer writes it; the gate run printed its sha256).
2. Send the 5 `.apk` files to the phone owner (chat attachment, cloud link), with the steps below.

## 4. Steps for the phone owner (copy as is)
1. Save the 5 files Bisect 1 to Bisect 5 on your phone. Tap the first one in your Files app or browser downloads.
2. If Android says installing unknown apps is not allowed: tap Settings, turn on "Allow from this source", go back, tap Install.
3. If Play Protect warns about an unknown app: tap "More details", then "Install anyway". Do the same for all 5 files.
4. Open "Bisect 1" and tap the big START button once. Do not touch the phone for 30 seconds. The screen flips back and forth by itself and counts "switch 1/20" to "switch 20/20".
5. Write down one answer for Bisect 1:
   - CLOSED BEFORE START: the app closed, or never showed the START button.
   - CRASH DURING SWITCHES: the app closed, or froze (stuck for more than 30 seconds). Also write the last "switch .../20" number you saw.
   - NO CRASH: you saw "DONE (variant 1, 20/20)".
6. Do the same with Bisect 2, 3, 4 and 5 (you may stop at the first crash), fill in the table and send it back.
7. When done, uninstall the 5 apps: long-press each icon, then Uninstall.

| # | Variant | CLOSED BEFORE START / CRASH DURING SWITCHES (switch no.) / NO CRASH | Phone + Android version |
|---|---------|--------------------------------------------------------------------|-------------------------|
| 1 | plain Kivy | | |
| 2 | raw Fbo | | |
| 3 | BoxShadow | | |
| 4 | KivyMD shadows off | | |
| 5 | KivyMD shadows on | | |

## 5. How to read it
Use the first variant whose answer is CRASH DURING SWITCHES:
- first crash at 3 (or at 5 with 4 clean) = BoxShadow, the leading theory; workaround = shadows off /
  elevation 0 on that phone. First crash at 2 = any Fbo. Crash at 1 = not Fbo at all (Kivy GL or the
  driver on any redraw). Crash at 4 but not 3 = KivyMD's transition / widgets without shadows.
- the switch number: every switch creates and first-renders new Fbos, so a crash at switch 1 is not
  more "first visit" than at switch 7; switch 1 only adds the first-ever GL work of the process (e.g.
  shader compiles). A crash only after many switches points to a repeated / timing / memory effect.
- No crash anywhere = the user's app has another factor (ask for their KV).
CLOSED BEFORE START is a different failure (startup: Python, imports, GL context; launch draws
no variant Fbo / BoxShadow, so it cannot be the ladder factor), not a switch crash: it does not count as a ladder answer; check the gate run of that variant and ask for the
Android version first.

## Untested
- Written before the first runs. Runs have happened since (matrix.yml, inspect.yml gates, devicelab.yml on a
  Pixel 5); their results are in the published reports (docs/cards.md "Report cards") and the run pages
  (docs/devicelab.md), not copied here.
- Desktop only (Windows, kivy 2.3.2, KivyMD master, materialyoucolor 3.0.4, autotest): all 5 reach
  20/20 + DONE with the per-switch numbers in the table above. A desktop pass does not prove the APK
  imports.
- Whether the nudge drives the same driver path as KivyMD's own BoxShadow updates is a judgement,
  not a measurement; that a `blur_radius` change makes BoxShadow's Fbo re-render (it re-sets the Fbo's
  uniforms) is read from Kivy's source, not measured (no per-frame render counter).
- The hypothesis itself (arriving screen's Fbo create + first render) comes from one crash log; the
  ladder tests it, it does not assume it is right.

# controlP top-down bisect (their real app, one group off at a time)

Code: `patches/controlp/bisect_toggles.diff` (adds `src/controlp/_bisect.py` + one import in `src/main.py`),
`tools/controlp_bisect.py` (the rule + JSON), `tests/test_controlp_bisect.py`.
Why: their app crashes on a Pixel 5 (Adreno 620, Android 11) about 60 ms into input -> explore (device lab DL1).
The kit above did not crash, so this goes top-down: their full app, with groups of its UI switched off.

## The rule
A variant = a point (groups off, ripple toggles, shadows). Every build: their pinned commit + `demo_device.diff;shadows_on.diff;bisect_toggles.diff`
(shadows on: the TopView BoxShadows draw) or `demo_device.diff;bisect_toggles.diff` (shadows off = as controlP ships; it disables shadows),
`android.api=34`, fat APK (x86_64 added), cache off. B0-B5 and T1/T2/W are shadows on, S0 is shadows off.
Groups (`app_config` keys; default = as shipped; always written):
- `input_fx: false` = input list rows lose the ripple, the list gets a plain scroll effect (no overscroll stretch), the list stops relabelling on choose.
- `menu: false` = explore's MenuView (MDRecycleView) becomes an empty widget.
- `bottom: false` = every BottomView becomes an empty spacer of the same height (taps unchanged).
- `topbar: false` = every TopView loses its title + power button; the app bar itself (and its BoxShadow) stays.
- `transition: "No"` = NoTransition instead of KivyMD's MDSharedAxis (empty = keep).
All of it is applied 0.5 s after start, after the widgets are built (so they are still constructed once).
Ripple toggles (`app_config` keys, written only when not the default; patched on the KivyMD classes at import, BEFORE
the app builds, so they reach every widget incl. ones made later, e.g. recycled explore items). KivyMD read: master a00c10c.
What the stock widgets really run (KivyMD a00c10c `kivymd/uix/behaviors/ripple_behavior.py`): lines 1024-1025 rebind
`RectangularRippleBehavior = M3RectangularRippleBehavior` and `CircularRippleBehavior = M3CircularRippleBehavior`, so
MDListItem (InputItem, MenuItem), its avatar, MDIconButton and MDButton all use `M3CommonRipple` (634); the old
stencil-only classes at 485 / 561 are dead code. M3CommonRipple gives every widget a PRIVATE Fbo when it is made
(`init_fbos` 697-708): `Fbo(size=50x50)` first, then `set_shader` (721-728) assigns `fbo.shader.fs` = ripple.glsl, i.e.
the shader is set AFTER the Fbo exists (the kivy#8098 pattern, a known old-Adreno crash). A tap adds, 1/30 s after touch
down (`call_ripple_animation_methods`), the Fbo + StencilPush, mask shape, StencilUse, Color, the Fbo texture as a
Rectangle (Ellipse for the avatar), StencilUnUse, unmask shape, StencilPop to `canvas.after` (768-802, group
`m3_ripple_behavior`); `_update_uniforms` (877-960, every frame and also inside each anim_complete) sets the shader
uniforms, resizes the Fbo to the widget (the first time at the tap itself, 50x50 -> widget size; `_call_ripple_animation_methods`
751 calls anim_complete before laying) and asks it to redraw; `anim_complete` (979-989) removes the group. So a tap = an Fbo
first drawn ~33 ms + a frame after touch down, close to the ~60 ms crash time (a fit, not a proof).
- `ripple_fbo_fs: "create"` = `M3CommonRipple.init_fbos` replaced: the Fbo gets the ripple shader AT CREATION
  (`Fbo(size=..., group=..., fs=RIPPLE_FS_STRING)`, the string loaded exactly as set_shader loads it) and no `shader.fs`
  is assigned later. set_shader has no other caller and the Fbo is never re-created (only resized), so no later fs set is
  left on this path (except Kivy's own `Shader.reload()` after a GL context loss, same as BoxShadow). Tests the #8098
  hypothesis; if it is clean it is a candidate upstream fix (a one-line change in KivyMD). Both halves of kivy#8098 fit:
  ripple.glsl sets `gl_FragColor` without `texture2D` (the shader shape that crashed on Adreno there), and its update says
  passing `fs` to `Fbo()` at creation avoids the crash.
- `ripple_stencil: false` = `M3CommonRipple.lay_canvas_instructions` replaced by the same minus StencilPush, mask shape,
  StencilUse, StencilUnUse, unmask shape, StencilPop: the Fbo, Color and textured Rectangle/Ellipse stay, same group, so
  anim_complete still removes all of it. The ripple is no longer clipped to rounded corners (it fills the widget box).
  The list's own ScrollView clip (a StencilView) STAYS: this removes the ripple's stencil, not every stencil.
- `list_ripple: false` = `ripple_effect` False on every `BaseListItem` (MDListItem, InputItem, MenuItem), set right after
  its `__init__`; a tap then adds nothing. Nothing else: unlike `input_fx`, scroll effects, observers and the state layer
  stay; the avatar's ripple stays too (not a list item; DL1's taps at x=540 do not hit it). Each list item still MAKES its
  ripple Fbo (with the late shader set) in `__init__`; it is just never drawn.
Runtime evidence (desktop Windows, Kivy 2.3.1 + KivyMD a00c10c, real GL window, NOT a phone):
`uv run --script tools/ripple_runtime_check.py` builds MDListItem + avatar, MDIconButton, MDButton per mode and runs one
ripple each. Result 74/74 PASS: every widget resolves to M3CommonRipple and gets the patched methods; shipped = Fbo made
without fs and `shader.fs` changed after creation on all 4; `create` = fs given at creation and never changed; stencil off
= the tap adds `Fbo, Color, BindTexture, Rectangle|Ellipse` and no Stencil*; list off = MDListItem adds nothing (the other
3 unchanged); in every mode anim_complete removes everything the tap added.

| variant | off | if it crashes / stays clean |
|---|---|---|
| B0 | nothing (control) | reserve |
| B1 | input_fx, menu | crash = not these two: run B2 / clean = run B3 |
| B2 | input_fx, menu, bottom, topbar | crash = transition, the rest, or the shadow alone / clean = bottom or topbar |
| B3 | input_fx | crash = menu / clean = input_fx |
| B4 | menu | splits B1 the other way |
| B5 | B2 + transition | the smallest app still holding the BoxShadows |
| S0 | nothing, shadows OFF | the reporter's shipped config: crash = the BoxShadow Fbo is NOT needed / clean = it is (with B0) |
| T1 | `ripple_fbo_fs: "create"` | clean = the late shader set on the ripple Fbo (kivy#8098 pattern) is needed: candidate KivyMD fix / crash = it is not |
| T2 | `ripple_stencil: false` | clean = the ripple's stencil mask is needed (fix: stencil-free ripple or a Kivy stencil reset) / crash = it is not |
| W | `list_ripple: false` | clean = turning all list ripples off avoids it: the workaround candidate for the app |

One clean run proves little (repeat any single clean). The last step is the smallest crashing set WITHOUT `shadows_on.diff`.
T1, T2 and W change one thing each against B0 (shadows on, all groups on); S0 changes only the shadows. Compare each with B0.
Not isolated by any variant: the per-frame Fbo resize / redraw of the ripple itself (if T1 and T2 both still crash and W is clean).

## Run it
1. Matrix: `uv run --no-project tools/controlp_bisect.py --only B1` (no `--only` = B0-B5; the ripple round = `--only S0,T1,T2,W`) -> paste as `builds` in Actions -> "build matrix" (label e.g. `controlP bisect B1`).
2. Gate + phone: `uv run --no-project tools/controlp_bisect.py <matrix run ID> <matrix run number> --only B1 [--attempt N]`
   prints per variant one inspect.yml JSON (emulator gate) and one devicelab.yml JSON (Pixel 5 `redfin`, API 30).
   Taps: `540,2000,5` first (a blank spot on Home; meant to dismiss an open notification shade, UNVERIFIED: check the video), then DL1's taps.
3. Gate PASS: logcat has `STUB bisect cfg` and one `STUB bisect off=<group> n=` per off group (n > 0; B5's transition logs `STUB bisect transition NoTransition` instead), `FAKEPIONEER <- 44FN`,
   `STUB bisect current=explore`, no traceback, and the last screenshot shows explore. Then the devicelab run.
   Ripple variants also need (EXPECTED lines, from the desktop run; never seen in logcat yet):
   T1 `STUB bisect ripple_fbo_fs=create patched=M3CommonRipple.init_fbos` at start and `STUB bisect ripple_fbo_fs=create n=` (n > 0) at setup;
   T2 `STUB bisect ripple_stencil=off patched=M3CommonRipple.lay_canvas_instructions` and at least one
   `STUB bisect ripple_stencil=off drawn=<class> n=` (a tap reached the patched ripple; a widget's FIRST tap prints 2, KivyMD lays it twice);
   W `STUB bisect list_ripple=off patched=BaseListItem.__init__` and `STUB bisect list_ripple=off n=` (n > 0).
   S0: the `STUB count` lines show `boxshadow=0` (shadows off).

## Log lines (logcat tag python)
`STUB bisect cfg {...} file=true|false`, `STUB bisect off=<group> n=<items changed>`, `STUB bisect transition <class>`,
`STUB bisect current=<screen> t=<monotonic s>` (each switch, at the moment `current` is set), then `STUB count screen=<s> boxshadow= fbo_boxshadow= elevated= fbo=`
for the arriving screen (and for every screen once at setup). `STUB bisect warn ...` = an attribute was missing; the app went on.
Ripple: `STUB bisect ripple_fbo_fs=create|ripple_stencil=off|list_ripple=off patched=<class.method>` (at import, once per active toggle),
`STUB bisect ripple_stencil=off drawn=<widget class> n=<k>` (each stencil-free ripple laid = each tap on a ripple widget),
`STUB bisect ripple_fbo_fs=create n=<ripple Fbos made so far>` and `STUB bisect list_ripple=off n=<list items so far>`
(at setup; widgets made later, e.g. recycled items, are covered but not counted there).

## Untested
Written before the first runs. Runs have happened since (inspect.yml gates, devicelab.yml on a Pixel 5); their results
are in the published reports (docs/cards.md "Report cards", docs/devicelab.md), not copied here. Before them, the controlP
part of `_bisect.py` was only compiled locally and the ripple toggles ran on desktop Kivy (below). The controlP attribute names come from
their source at the pinned commit and KivyMD master a00c10c, which the build fetches unpinned (check it is unchanged).
The ripple toggles: checked against KivyMD a00c10c's source by ast (tests/test_controlp_bisect.py, aliases followed) and run
on desktop (tools/ripple_runtime_check.py, Kivy 2.3.1 where the build uses 2.3.2; desktop GL, not Adreno) before the
S0 / T1 / T2 / W gates and phone runs; what those showed is in the published report.
