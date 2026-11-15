# Q-B hardware bisection kit: 5 test APKs for a phone that crashes

For people and LLMs. Spec: QUEUE.md "Q-B HARDWARE BISECTION KIT". Code: `stub_kivymd/ladder.py` (the
rule), `stub_kivymd/bisect_app.py` (the app), `.github/workflows/matrix.yml` (one run, 5 APKs).

## Why
A KivyMD app crashes in the GPU driver (native SIGSEGV, nested Fbo draw) in the first frames after a
screen change. Emulators render in software and cannot show a driver crash, so the phone owner runs 5
small APKs. Each adds one factor; the FIRST one that crashes names the trigger.

## The ladder (one generator)
`ladder.py`: a variant is a point (ui, extra); variants 1..5 = (kivy, kivymd) x (plain, fbo, shadow)
in that order, minus (kivymd, fbo) (kept out to stay at 5; set `ui` / `extra` directly to run it).
Screen 2 always holds 3 cards: Kivy `Button`s (ui kivy) or elevated `MDCard`s (ui kivymd).

| # | name (app title `Bisect N <name>`) | package | QUEUE.md variant | screen 2 count line (desktop) |
|---|---|---|---|---|
| 1 | Kivy plain | org.khr.bisect1 | plain Kivy ScreenManager + SlideTransition | boxshadow=0 fbo=0 |
| 2 | Kivy Fbo | org.khr.bisect2 | 1 + one raw Kivy Fbo | boxshadow=0 fbo=1 |
| 3 | Kivy BoxShadow | org.khr.bisect3 | 1 + 3 widgets with Kivy BoxShadow | boxshadow=3 fbo=3 |
| 4 | KivyMD plain | org.khr.bisect4 | MDScreenManager + MDSharedAxis, elevated cards, shadows OFF | boxshadow=0 elevated=3 |
| 5 | KivyMD BoxShadow | org.khr.bisect5 | 4 with stock shadows ON | boxshadow=3 elevated=3 |

Variants 1-3 never import kivymd (`kivymd_loaded=False` in the done line); all 5 APKs carry the same
requirements, so they differ only by `app_config` + package name / title. Shadows OFF = stubkit's
Factory swap (no BoxShadow, no BoxShadow Fbo at all). START / status text are plain Kivy widgets in
every variant.

What the app does: screen 1 shows `Bisect N <name>` and a big START. One tap = 20 automatic switches
screen 1 <-> screen 2, each after the transition's duration + 0.3 s (Slide 0.7 s, MDSharedAxis
0.5 s), then `DONE (variant N, 20/20)`. Logcat (tag `python`): `STUB bisect variant=N ui= extra=`,
`STUB gl ...` (the GPU line), `STUB count ...` after each switch, `STUB bisect variant=N switch=k
screen=s1|s2`, `STUB bisect done variant=N switches=20/20 kivymd_loaded=<bool>`.

## Build: ONE matrix run (Actions -> "build matrix" -> Run workflow)
label `Q-B bisect kit`, builds = this JSON (regenerate: `uv run --no-project stub_kivymd/ladder.py`):

```json
[{"name":"bisect1","label":"Q-B bisect 1 Kivy plain","app":"stub_kivymd","requirements":"python3,kivy==2.3.2,https://github.com/kivymd/KivyMD/archive/master.zip,materialyoucolor==3.0.4,asynckivy,asyncgui,pillow","app_config":{"variant":1},"extra":"package.name=bisect1;title=Bisect 1 Kivy plain;android.api=36"},{"name":"bisect2","label":"Q-B bisect 2 Kivy Fbo","app":"stub_kivymd","requirements":"python3,kivy==2.3.2,https://github.com/kivymd/KivyMD/archive/master.zip,materialyoucolor==3.0.4,asynckivy,asyncgui,pillow","app_config":{"variant":2},"extra":"package.name=bisect2;title=Bisect 2 Kivy Fbo;android.api=36"},{"name":"bisect3","label":"Q-B bisect 3 Kivy BoxShadow","app":"stub_kivymd","requirements":"python3,kivy==2.3.2,https://github.com/kivymd/KivyMD/archive/master.zip,materialyoucolor==3.0.4,asynckivy,asyncgui,pillow","app_config":{"variant":3},"extra":"package.name=bisect3;title=Bisect 3 Kivy BoxShadow;android.api=36"},{"name":"bisect4","label":"Q-B bisect 4 KivyMD plain","app":"stub_kivymd","requirements":"python3,kivy==2.3.2,https://github.com/kivymd/KivyMD/archive/master.zip,materialyoucolor==3.0.4,asynckivy,asyncgui,pillow","app_config":{"variant":4},"extra":"package.name=bisect4;title=Bisect 4 KivyMD plain;android.api=36"},{"name":"bisect5","label":"Q-B bisect 5 KivyMD BoxShadow","app":"stub_kivymd","requirements":"python3,kivy==2.3.2,https://github.com/kivymd/KivyMD/archive/master.zip,materialyoucolor==3.0.4,asynckivy,asyncgui,pillow","app_config":{"variant":5},"extra":"package.name=bisect5;title=Bisect 5 KivyMD BoxShadow;android.api=36"}]
```

Everything else comes from `stub_kivymd/spec_overrides.txt`: p4a develop, android.ndk 29, archs
arm64-v8a, Kivy 2.3.2, KivyMD master; `extra` raises android.api to 36 (the reporter's). Cache: `off`
(cold, the only evidence). Artifacts `build-<run>-bisect1..5` hold the debug APKs; the `facts` job
prints package / targetSdk / ABIs / sha256 of all 5.
`materialyoucolor==3.0.4`: p4a develop's recipe ships 2.0.10, which has no
`materialyoucolor.dynamiccolor.color_spec`; KivyMD master imports it in `theming.py` (it declares
`>= 3.0.3`), so variants 4-5 crash at import without the pin (seen on the emulator for the stub). p4a
turns `name==ver` into `VERSION_<name>`, so the recipe fetches the GitHub release tarball v3.0.4
(exists; setuptools + pybind11 build, like 2.0.10's setup.py). 3.0.4 = the version the desktop check
ran. Once `spec_overrides.txt` carries the pin, the `requirements` key can be dropped from the JSON.

## Emulator smoke test (optional, x86_64, before sending)
inspect.yml, one run per variant (it adds x86_64): app empty (= stub_kivymd), app_config
`{"variant": N}`, extra `requirements=<the requirements above>;android.api=36` (extra wins over
spec_overrides), taps `540,1900,30` (START = bottom part of screen 1 on pixel_6), launch_wait 30.
Pass = the screenshot after the tap shows `DONE (variant N, 20/20)`, logcat shows 20 `switch=` lines,
`app pid at end` is set. A software emulator CANNOT clear a GPU-driver crash: this only proves the app
runs. (Do not use `autotest` there: it stops the app after DONE, which reads like a crash.)

## Instructions for the phone owner (copy as is)
1. Install the 5 apps "Bisect 1" to "Bisect 5" (Android may ask you to allow installing apps from this source: allow it).
2. Open "Bisect 1" and tap the big START button once.
3. Wait about 20 seconds without touching anything: the screen flips back and forth by itself.
4. Write down NO CRASH if you see "DONE (variant 1, 20/20)", or CRASH if the app closes or freezes.
5. Do the same with Bisect 2, 3, 4 and 5 (you may stop at the first CRASH), then send us the table below.

| # | Variant | CRASH / NO CRASH | Phone + Android version |
|---|---------|------------------|-------------------------|
| 1 | plain Kivy | | |
| 2 | raw Fbo | | |
| 3 | BoxShadow | | |
| 4 | KivyMD shadows off | | |
| 5 | KivyMD shadows on | | |

## How to read it (QUEUE.md)
First crash at 3 (or at 5 with 4 clean) = BoxShadow, the leading theory; workaround = shadows off /
elevation 0 on that phone. First crash at 2 = any Fbo. Crash at 1 = not Fbo at all (Kivy GL or the
driver on any redraw). Crash at 4 but not 3 = KivyMD's transition / widgets without shadows. No crash
anywhere = the user's app has another factor (ask for their KV).

## Untested
- Nothing here has run on GitHub or Android yet: matrix.yml, the materialyoucolor 3.0.4 recipe build,
  android.api 36, the APKs, the emulator taps (START position), the facts table.
- Desktop only (Windows, kivy 2.3.2, KivyMD master, materialyoucolor 3.0.4, autotest): all 5 reach
  20/20 + DONE with the counts in the table above. A desktop pass does not prove the APK imports.
- The Fbo in variant 2 re-renders on every move of the widget (as BoxShadow does on its own changes);
  whether that matches the driver path BoxShadow takes is a judgement, not a measurement.
