# inspect.yml: look at an APK on GitHub

For people and for LLMs picking this up later. Workflow: `.github/workflows/inspect.yml`
(Actions tab -> "inspect apk" -> Run workflow, or workflow_dispatch via the API / `gh workflow run`).

## What it does
1. **Get an APK** (exactly one source; the `check` job refuses mixes): download `apk_url`, OR take
   the APK artifact of ANOTHER run of this repo (`artifact_run` + `artifact_name`, e.g. a matrix.yml
   build; no rebuild), OR build one through `build.yml` (reused as a `workflow_call`): a public
   `repo` + `ref`, or an app dir of this repo (`app`, default `stub_kivymd`).
   A build ADDS `x86_64` to the app's `android.archs` (the emulator is x86_64), unless `static_only`.
   With `apk_url` or an artifact, the build inputs (repo, ref, app, archs, extra, app_config, image, cache) must
   stay empty / default (a set one would be silently ignored, so the run fails instead).
   **Artifact source**: the `fetch` job (the ONLY job with `actions: read`) downloads the artifact
   with `actions/download-artifact` (`run-id`, this repository, the run's own token), requires
   exactly one `.apk` in it and, unless `static_only`, an x86_64 lib (`lib/x86_64/`; fails with a
   clear message otherwise), and re-uploads that APK as `apk-input-<n>-a<attempt>` (kept 3 days: enough to
   re-run a failed inspect job) so the inspect job reads it by the same path as a built APK.
   Artifacts expire after 14 days. A failed download prints why (run ID vs run number, expiry, name).
   No build also means `image` and `cache` must stay default (`cache: off`).
2. **Static facts** (always): `aapt2 dump badging` (package, targetSdk, minSdk, ABIs, permissions),
   the APK sha256, and the bundled Python packages (`tools/apk_pkgs.py`: libpython version,
   `*.dist-info` / `*.egg-info` found in the APK and in archives nested in it, plus site-packages
   names without metadata).
3. **Emulator run** (unless `static_only`): `reactivecircus/android-emulator-runner`, KVM, the
   `google_apis` x86_64 image at `api_level`, device `profile`. `tools/emu_run.sh` installs (`-g`),
   launches, waits `launch_wait` s, then runs `taps`, with a `screencap` PNG after launch and after
   each tap, and saves the emulator's own logcat. The emulator step retries once if it fails
   (the action has no retry input; the script itself always exits 0, so a failure = the emulator).
   Before install it SETTLES (bounded): `sys.boot_completed`, the launcher focused (<= 60 s each),
   then 10 s idle (env `SETTLE`). Before launch, before the launch shot and before EACH tap it
   dismisses OTHER apps' ANR / crash dialogs (found in `dumpsys window windows`; a "Pixel Launcher
   isn't responding" dialog covered the launch shot and ate the first tap in 2 of 7 Q-A runs and 3
   of 5 gate runs): `am broadcast CLOSE_SYSTEM_DIALOGS`, else a tap on the dialog's `Wait` /
   `Close app` button (uiautomator), else BACK (only when that dialog has focus). The app's OWN ANR / crash dialog is left open (a
   result). Everything found and how it went: `system_dialogs.txt` (+ the summary).
4. **Screenshots without clicking**: the `shots` job (the ONLY job with `contents: write`) makes one
   contact sheet (`tools/contact_sheet.py`, Pillow via uv) and pushes it plus every PNG to the
   orphan branch `shots` under `shots/<run_id>/`. Its summary prints the raw URLs
   (`https://raw.githubusercontent.com/<owner>/<repo>/shots/shots/<run_id>/sheet.png`) and embeds
   the sheet; the same URLs are echoed to the step log (`gh run view --log` shows them). A raw
   PNG link pasted in Discord unfurls as an inline image.
   It also writes a Discord **card page** (`shots/<run_id>/index.html`, served by GitHub Pages:
   one embed with title + result line + sheet): see [cards.md](cards.md).
   And `shots/<run_id>/inputs.json`: every dispatch input of the run, so a report can show how to recreate it.
5. **Summary**: inputs, build image digest, emulator image + fingerprint, cache level + hit,
   COLD/WARM, static facts, logcat hits (Python tracebacks / errors / FATAL, first traceback,
   first lines of the app's `python` tag), screenshot count, and the GPU warning in bold.

Artifacts (14 days): `build-<n>` (build.log, spec, APK; `build-<n>-<name>-a<attempt>` when built by matrix.yml) and `inspect-<n>-a<attempt>` (PNGs, logcat, badging,
python_packages.md, install/launch output, system_dialogs.txt; plain `inspect-<n>` before 2026-11-15 push 2).
The shots job downloads the name the inspect job outputs, so a re-run in a later attempt still finds it.

## Inputs
| input | meaning |
|---|---|
| label | run name: what question this answers |
| apk_url | https URL of an APK; set = no build |
| artifact_run | run ID (the number in `.../actions/runs/<id>`) of another run of THIS repo; set = no build; digits only |
| artifact_name | that run's artifact holding the APK, e.g. `build-<run_number>-bisect1-a1` (matrix.yml) or `build-<run_number>` (build.yml); `A-Z a-z 0-9 . _ -`, 1-100; needs artifact_run |
| repo / ref | public GitHub repo `owner/name` + branch/tag/commit to build (empty repo = this repo) |
| app | app dir holding `main.py`: in this repo (default `stub_kivymd`) or in `repo` (default `.`) |
| archs | `android.archs` (empty = the app's own); `x86_64` is appended unless static_only |
| extra | more spec overrides, `;` separated (`android.api=35;p4a.branch=develop`) |
| app_config | JSON baked into the APK as `app_config.json` next to main.py |
| static_only | true = no emulator |
| api_level | emulator API (default 35) |
| profile | emulator device (default `pixel_6`, 1080x2400; the summary prints `wm size`) |
| taps | `x,y[,wait_s]` steps separated by `;` (wait default 5 s) |
| launch_wait | seconds before the first screenshot (default 30; first start unpacks the app) |
| cache | `off` (cold) / `sdk` / `full`, as in build.yml, plus the built-APK cache when not `off` |
| image | buildozer container image (empty = build.yml's default, `ghcr.io/kivy/buildozer:latest`) |
| fail_on_death | true = the inspect job FAILS at its last step (after the artifact upload; the shots job still publishes) when the verdict is `APP DIED` or `APP NOT INSTALLED`; default false (stays green) |
| patches | build only: diffs of THIS repo applied to the source before the build, `;` separated, each `patches/<name>.diff` (below) |
| sidecar | a fake device started on the runner before the app: `tools/fakes/<name>.py` (below); empty = none |
| adb_reverse | ports forwarded device -> runner before launch, `;` separated, each 1-65535 (e.g. `8102;18080`); empty = none |

Spec layering in a build (build.yml): the app's own `buildozer.spec`, else `buildozer init` ->
the app dir's `spec_overrides.txt` (key=value lines) -> non-empty form inputs -> `extra` ->
`android.archs+=<add_archs>` (`tools/patch_spec.py` supports `key+=item` = append if missing).
Patches come BEFORE all of that (they may change the spec too).
Base spec, first found (since 2026-11-16; the build log and summary print `base spec: ...`):
(1) `buildozer.spec` in the app dir; (2) `buildozer.spec` at the source root (the fetched repo's root, else
this repo's root) when its `[app] source.dir` is the app dir: the common "spec at the root, code in `source.dir`"
layout (e.g. controlP: `app` = `src`, root spec has `source.dir = src`). It is copied with `source.dir = .`, since
the build dir holds the app dir's contents. Other relative paths in that spec are NOT rewritten: the build
prints a warning listing the keys present (`p4a.local_recipes`, `p4a.hook`, `icon.filename`, `presplash.filename`,
`android.add_src`, `android.add_resources`, ... unless written with `%(source.dir)s`). (3) `buildozer init`.
A root spec that is a symlink, cannot be parsed, or has a `source.dir` outside `[A-Za-z0-9_./-]` falls back to init.
So `repo` builds whose app dir has no spec now use the root spec when its source.dir matches: runs before this
(e.g. controlP R1-R3, built from `buildozer init`) are NOT comparable with later ones; the summary's
`base spec:` line records which spec each run used. A root spec whose `source.dir` is another dir is not used, and the
log says why. (Before this, controlP runs R1-R3 fell back to `buildozer init` and failed.)
`tools/patch_spec.py` replaces the UNCOMMENTED key when a spec has both `#key = ...` and `key = ...`, and drops a
multi-line value's continuation lines (e.g. `requirements` over several lines).

## Patches (build.yml / inspect.yml / matrix.yml input `patches`)
- A patch is a `git diff` file in this repo under `patches/` (e.g. `patches/controlp/insets_fix.diff`).
- Each path must match `patches/[A-Za-z0-9._/-]+.diff` with no `..`; anything else fails the run at once.
- build.yml applies them in the given order with `git apply --verbose`, in the root of the source being built.
- That is the fetched repo's root when `repo` is set (not the `app` dir), else this repo's root.
- Any patch that does not apply fails the run: a patched build never silently runs unpatched.
- The build summary lists every applied patch with its sha256; `patches_applied.txt` is in the build artifact.
- The patch list (paths + sha256) joins the `full` and `apk` cache keys, so a patched APK is never restored for an unpatched run.
- Text before the first `diff --git` line is a comment (git apply ignores it): say what the patch does and which upstream commit it is against.
- `.gitattributes` keeps `patches/**` byte-exact (`-text`): no line-ending conversion on any OS.
- matrix.yml takes `patches` per element of its `builds` JSON.

## Sidecar + adb_reverse: fake devices on the runner
- `sidecar` = a script in `tools/fakes/` (stdlib Python), started with `python3 -u` on the runner before the emulator boots.
- It keeps running through the emulator steps. Its output is `sidecar.log` in the inspect artifact.
- The summary says whether it was still running at the end and shows its first 40 lines.
- `adb_reverse` = ports. After install and before launch, `tools/emu_run.sh` runs `adb reverse tcp:P tcp:P` for each.
- Then the app's `127.0.0.1:P` on the emulator reaches the runner's port P, i.e. the sidecar.
- The result is `adb_reverse.txt` (+ the summary). A failed port is also in `errors.txt`.
- The emulator retry (attempt 2) sets the ports again on the new emulator.
- Both need the emulator (refused with `static_only`). Both empty = exactly the old behaviour.
- The summary also shows the app's `STUB ...` lines (logcat tag python) in their own block.

## Driving controlP (yabb85/controlP) with a fake Pioneer player
The app leaves its Home screen only after it finds a Pioneer network player on the LAN (SSDP), then
talks to it over TCP port 8102 and fetches its UPnP description (+ album art) over HTTP.
An emulator on a CI runner has no such player, so:
- `tools/fakes/pioneer.py` is a fake player: HTTP on 18080 (`/description.xml`, `/art/<name>.png` generated PNGs)
  and the Pioneer text protocol on 8102 (power, input, `?GAP` screen, `?GIA` list lines, `?GIC` art, `GHP` open line, `PB` keys).
- It replies to every command the app reads a reply for, and to none of the others (a stray reply would be read as
  the answer to the next command). It never closes a connection (the app would spin on EOF).
- Menu: root "Music Server" -> 5 folders -> 6 tracks -> play screen (FitImage loads the art over HTTP).
- Every request / reply is a `FAKEPIONEER ...` line in `sidecar.log`.
- `patches/controlp/fake_pioneer.diff` makes `scan()` skip SSDP and use `http://127.0.0.1:18080/description.xml`.
  The rest is their real code (requests + lxml for the description, api.py over TCP).
- Run it with: repo `yabb85/controlP`, ref `cad5d5c626516dcbf18719194c92e63f06128d62`, app `src`,
  patches `patches/controlp/fake_pioneer.diff`, sidecar `tools/fakes/pioneer.py`, adb_reverse `8102;18080`.
- Other controlP patches (all against cad5d5c, combinable unless said):
  `insets_fix.diff` (Bug 1 fix: pads a root box by the system bar insets, logs `STUB insets ... applied=`),
  `shadows_on.diff` (removes their `disable_shadows()` call: KivyMD BoxShadow + its Fbo per elevated widget),
  `demo_device.diff` (the same fake INSIDE the app, for a real phone with no runner: devicelab.yml; never with fake_pioneer.diff).
- `demo_device.diff` carries a byte-identical copy of `tools/fakes/pioneer.py`. After changing the fake, regenerate it:
  copy the fake to `src/controlp/pioneer/_fake_pioneer.py` in a pristine LF checkout of cad5d5c (plus the scan() hunk),
  run `git diff --no-index` against the pristine tree, fix the `a/` `b/` prefixes, keep the comment header.
- Tap coordinates (pixel_6, 1080x2400; GUESSES from the kv layouts until a launch screenshot is read):
  Home device card `540,600`; input screen "Music Server" (4th list row) `540,800`;
  explore first row `540,360` (folder), then `540,360` again (track -> play screen).
- Their Home card image is `src/controlp/data/images/N-50A.jpg` (the fake's modelName is `N-50A`).
- Their spec does not list `requests` (upnp.py imports it). If the launch logcat shows
  `ModuleNotFoundError: requests`, add `requirements+=requests` to `extra` (it would then differ from their build).

## Built-in test apps
- `stub/`: minimal Kivy label (build.yml's default; unchanged).
- `stub_kivymd/`: KivyMD 2.x (git master, 2.0.1.dev0) + Kivy 2.3.2, p4a develop, targetSdk 35,
  archs arm64-v8a (+ x86_64 from inspect). MDScreenManager with 3 MDScreens, a small MDTopAppBar,
  an elevated MDCard holding a nested elevated MDCard and an elevated MDButton. Tapping the big card
  (screen center: `540,1200` on pixel_6) or the button goes to the next screen. Prints
  `STUB config {...}` and `STUB screen <name>` to stdout = logcat tag `python`, so the summary
  shows whether each tap switched screens. Files: `main.py` (dispatcher: `variant` 0 = this app,
  `showcase.py`; 1..5 = the Q-B bisect ladder, `bisect_app.py`, see docs/bisect.md), `stubkit.py`
  (kivymd-free helpers + config). Config (later wins): `DEFAULTS` in stubkit.py
  `{"shadows": true, "transition": "Slide", "count": true, "insets": false, "autotest": 0,
  "autotest_touch": false, "variant": 0, "ui": "", "extra": "", "switches": 20}` -> `app_config.json` (input `app_config`)
  -> env `STUB_<KEY>` (desktop, e.g. `STUB_SHADOWS=0`).
  - `transition`: a Kivy screenmanager name (`Slide`, `Fade`, `No`, ...) or a KivyMD one (`MDSlide`,
    `MDFadeSlide`, `MDSharedAxis`), applied one frame after build and printed as
    `STUB transition <class>`. (Before 2026-11-15 it was set in build() and MDScreenManager's
    next-frame `check_transition` silently replaced any non-MD one with MDSharedAxis: older runs
    all ran MDSharedAxis.)
  - `shadows: false`: Factory's `BoxShadow` is swapped for a no-op group before the KV builds, so
    the `<CommonElevationBehavior>` kv rule (which adds a BoxShadow + its Fbo to EVERY elevated
    widget, even at alpha 0 / elevation 0) creates none. (The old class-level `shadow_color`
    hack removed no BoxShadow.)
  - `count`: after start and after each switch (on_enter):
    `STUB count screen=<name> boxshadow=<n> fbo_boxshadow=<n> fbo_transition=<n> elevated=<n> fbo=<n>`
    (current screen's tree; `fbo_transition` = cumulative Fbos made by Kivy shader transitions;
    `fbo` = every Fbo instruction in the tree, BoxShadow's included; `fbo=` added 2026-11-15).
  - insets: the system bar insets are ALWAYS read via pyjnius (`getRootWindowInsets`, API 30+
    `systemBars()`) at the first frame and again 1 s later and printed as
    `STUB insets top= bottom= left= right= applied=<bool>` (px; `n/a` = not readable, e.g. desktop),
    so the overlap has a logged number in every run. `insets: true` also PADS the root by them
    (`applied=True`). (Before 2026-11-15 push 2, `insets: false` skipped the read and printed 0.)
    The reader asks `systemBars() | displayCutout()` (a camera cutout is not a system bar; since
    2026-11-17) and first prints `STUB insets parts bars=t,b,l,r cutout=t,b,l,r` so a run shows which part sets the inset.
  - `autotest: N`: N automatic switches 1.5 s apart, then the app stops (desktop checks).
    `autotest_touch: true` switches through the REAL input path instead of code: the mouse moves
    onto the big card (KivyMD hover) and a touch down/up goes through the EventLoop
    (`STUB tap x= y= screen=`). Desktop check (2026-11-15): with `materialshapes` uninstalled, code
    switches pass and the first touch dies with the Android traceback (card -> kivymd.uix.list ->
    fitimage -> materialshapes); with it installed, 3 touch switches pass.
  - Always: `STUB gl vendor=... renderer=... version=...` at start (the GPU line for logcat).
  Requirements include `materialshapes` + `pycairo` (since 2026-11-15 push 2): kivymd's fitimage /
  loadingindicator import it, and the FIRST TOUCH reaches fitimage (MDCard hover / state layer ->
  `kivymd.uix.list` -> fitimage), so without them every tap killed the app (7 cold inspect runs, 2026-11-15).
  Edge-to-edge OPT-OUT (off by default): input `extra` = `android.add_resources=android_res`.
  It adds `stub_kivymd/android_res/values-v35/styles.xml`, which redefines `KivySupportCutout`
  (p4a develop's manifest hard-codes it as the ACTIVITY theme, so `android.apptheme` alone does
  not reach the activity) with `android:windowOptOutEdgeToEdgeEnforcement=true`. Assumes the
  default `android.display_cutout = never`; ignored by Android at targetSdk >= 36.
  **UNTESTED on Android**: the opt-out, `insets`, and the GL / count lines on a device.
  Desktop check (2026-11-15, Windows, Python 3.13, kivy 2.3.2 + KivyMD master, `STUB_AUTOTEST=3`):
  Slide / Fade / MDSharedAxis each stay applied; per screen `boxshadow=4 fbo_boxshadow=4
  elevated=4` with shadows on, `boxshadow=0 fbo_boxshadow=0` off; `fbo_transition` grows by 2
  per switch only with Fade (0 for Slide, MDSharedAxis).

Example dispatch for the first goal (edge-to-edge check):
label `stub_kivymd edge-to-edge api35`, app empty, taps `540,1200,4;540,1200,4`, cache `off`.

## How to read results
1. Summary of the `inspect` job first. Its FIRST line (emulator runs) is the app state:
   `**APP DIED: FAIL**` (no app pid at the end; plus the first Python traceback's exception line
   when logcat has one), `**APP NOT INSTALLED: FAIL**` (adb install failed; its last line shown),
   `**ADB LOST DEVICE: UNKNOWN**` (adb no longer saw the emulator), `**APP OK**` (alive at the end;
   `, but N Python traceback(s) in logcat` when there were any), or
   `**APP STATE UNKNOWN**` (no pid_at_end.txt: the emulator run did not finish). `tools/emu_run.sh`
   writes these states to `pid_at_end.txt`. On the emulator retry (attempt 2), attempt 1's files
   are moved to `out/prev_attempt_1/` first, so the summary reports only the last attempt. The workflow stays green when the app dies
   (unless `fail_on_death`): read this line, not the check mark. The same verdict is a run
   ANNOTATION (error for APP DIED / NOT INSTALLED, notice for APP OK), shown at the very top of
   the run page above every job summary, and its word is in the card description.
   Then the bold GPU line, static facts (targetSdk >= 35 = Android 15+ enforces edge-to-edge for
   this APK), logcat hits.
2. The `shots` job summary: the contact sheet. Edge-to-edge overlap = app content (e.g. the top
   app bar) drawn under the status bar / navigation bar.
3. Evidence rule (CLAUDE.md cache protocol): only a COLD run is evidence. COLD = NO cache restored
   anything (actions/cache `cache-hit` is not `true` for sdk, full or apk); WARM = any hit. It
   follows the actual hits, not the `cache` input: `cache: sdk` whose key missed is COLD (the SDK /
   NDK were downloaded fresh). The summary prints each cache as `HIT` / `MISS` / `not used` /
   `skipped (apk hit)` with its exact key. (Before 2026-11-15 any `cache` != `off` printed WARM even
   on a total miss.) `apk_url` / artifact runs say `APK input (no build)`: the APK itself is the
   input. The summary's `from:` names the source (`apk_url`, `artifact <name> of run <id>` with a
   link, or `build <source id>`); the card description ends with `from run <id> artifact <name>`
   and links the source run.

## Limits
- **No GPU / hardware bugs**: the emulator renders with SwiftShader (software), not e.g. Adreno
  or Mali. A driver-specific rendering bug (black screens, broken shadows on one GPU) can pass here.
  What it CAN catch: Python tracebacks, startup crashes, missing modules, broken layouts, inset
  / edge-to-edge overlap, wrong permissions / targetSdk.
- arm64-only APKs (e.g. an `apk_url` without x86_64) may not install or run on the x86_64
  emulator (API 30+ images can translate some arm64 code; untested here). `install` in the summary
  shows `INSTALL_FAILED_NO_MATCHING_ABIS` when it fails.
- Launch timing is a fixed wait, not a "rendered" signal: raise `launch_wait` if the first shot is black.
- A fresh emulator, not the reporter's phone: OEM skins, display cutouts and gesture-nav settings differ.

## Privacy (public repo)
We build a reporter's PUBLIC code ourselves and read OUR runner's logcat. Never upload a
reporter's own device logcat, screenshots or APK here unless they published it themselves;
never put reporter names in labels, commits or docs. Screenshots land in a public branch.

## Security
- `workflow_dispatch` only: only collaborators can start it. No `pull_request_target` /
  `issue_comment` / other triggers strangers can fire.
- Every input reaches the shell via `env:` (never `${{ inputs.x }}` inside `run:`); the `check`
  job validates apk_url (one https URL), artifact_run (digits), artifact_name (strict charset),
  api_level, profile, launch_wait, taps, patches (`patches/...diff`, no `..`), sidecar
  (`tools/fakes/<name>.py`: only scripts of this repo run) and adb_reverse (port numbers) before any build.
- `contents: write` only on the `shots` job; the push uses the run's own `GITHUB_TOKEN`
  (`tools/push_shots.sh`, shared with report.yml's `publish` job).
  `actions: read` only on the `fetch` job (artifact source), pinned to `github.repository`.

## Design decisions (dated)
- 2026-11-14: spec approved by the author; build reused via `workflow_call` on build.yml (one
  build path, not a copy); build.yml moved to env-only inputs at the same time.
- 2026-11-14: APK cache = exact key over image digest + source id (repo@resolved sha:app, or
  local:<app>:<hash of its tracked files>) + requirements / p4a / archs / add_archs / extra /
  app_config / command. No restore-keys. On when `cache` != off; a hit skips the build and the run
  is WARM. Author: "can't we cache the apk".
- 2026-11-14: screenshots as one contact sheet on an orphan branch so a raw link unfurls in Discord
  (author: "can't we do something where the discord embed is the screenshots").
- 2026-11-15: `artifact_run` + `artifact_name` = any APK artifact of a run of this repo (not a
  matrix-only input), so the Q-B gate runs on the matrix's own fat APKs without 5 rebuilds; a
  separate `fetch` job re-uploads it so `actions: read` stays off the inspect job.
- 2026-11-14: generic mechanisms over one-offs: `spec_overrides.txt` per app dir, `app_config`
  JSON for any app, `key+=item` in patch_spec.py, `add_archs` in build.yml.
