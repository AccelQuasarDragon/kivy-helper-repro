# QUEUE: what is planned, building, done (REWRITTEN IN PLACE, never appended)
> SUPERSEDED for STATUS (author, 2026-11-14): item status, order and done-ness live in the author's private task tracker
> (lane "kivy help": Q-0 0d58bd2b, Q-A 80b79c49, Q-B 6d8daeb1, Q-C e757e287, Q-D e6a626a6). This file stays as the
> DETAIL SPEC of each item (runs, hypotheses, acceptance); do not track status here.
Last rewrite: 2026-11-14 (created). OWNER: the discussion / parent chat only (one owner per file). Build and inspection
agents never edit this file: they build the item named to them and hand back a result line (run link, COLD/WARM, answer to
the run's question); the owner moves the item and records the result here and in CLAUDE.md "Log".
PUBLIC REPO: no local paths, usernames, emails, chat links or reporter names in this file (CLAUDE.md privacy check applies).

## HOW THIS QUEUE WORKS (every new chat reads this first)
- Each item: ID, STATUS (READY / BLOCKED on X / RUNNING / DONE / LATER), OWNER (model + role), BUDGET, DEPENDS, ACCEPTANCE.
- OWNERS: Opus subagent = inspection, dispatching runs, reading logs, review, mechanical edits. Fable = hard builds whose
  result cannot be checked on the runner. Builder != reviewer: whatever Fable builds, Opus reviews, and the reverse.
- EVIDENCE (CLAUDE.md "Cache protocol"): the FIRST run of a new question is cold (`cache: off`); iterate on `sdk`; the run
  that backs any claim posted anywhere is cold again. A claim cites a cold run's link, never a warm one.
- EVERY RUN states, in its `label`, its QUESTION and its HYPOTHESIS before it is dispatched; the hand-back states the answer
  (confirmed / refuted / inconclusive + why). A run with no stated question does not count toward an item's acceptance.
- HARD ORDERS (the only gates): Q-0 before Q-A; Q-A's renderer check (A-1) before any "software rendering cannot catch it"
  claim; Q-B is built on GitHub, never on a local machine; Q-D does not start before the course deadline work allows it.

## CONTEXT (2026-11-14)
A user's KivyMD app (Kivy 2.3.x, KivyMD 2.0.1.dev0, Python 3.14) crashes natively on screen change: SIGSEGV in the Adreno
GLES driver (Adreno 618, Android 11). Native stack: kivy fbo -> instructions -> vbo -> driver. The author ACCEPTS that the
crash is the phone's hardware / driver; the goal is to PINPOINT the trigger and give the user a workaround, not to fix the driver.
Verified in source (KivyMD 2.0.0 dev, Kivy 2.3.1):
- MDScreenManager forces MDSharedAxisTransition on its first frame (kivymd/uix/screenmanager.py ~L214-224); no KivyMD
  transition uses an Fbo. Kivy's ShaderTransitions (Fade / Wipe / FallOut / RiseIn) DO use one.
- Kivy BoxShadow holds an Fbo (kivy/graphics/boxshadow.pxd L20); KivyMD draws every elevation shadow with BoxShadow
  (kivymd/uix/behaviors/elevation.py L407). M3*RippleBehavior also uses an Fbo, but stock widgets do not use it.
LEADING THEORY (inferred, not yet tested): the incoming screen's elevated widgets create / render BoxShadow Fbos during
the switch and the Adreno driver crashes on that path.
SECOND ISSUE: on the user's Android 15 phone the status / nav bars overlap the UI = probably forced edge-to-edge at targetSdk 35.
EXPECTED OUTCOME of Q-A: the emulator renders with SwiftShader (software), so it will NOT crash. That is why Q-B exists.
Author's plan (2026-11-14): "investigate with github runner, budget is like 2 hours or ~15 github runs"; "if github checks
out b/c it's software rendering and we can't catch hardware fail, we give 5 tests to run to investigate the hardware to
bisection pinpoint the target".

## Q-0 THE INSPECT WORKFLOW (prerequisite)
STATUS: RUNNING (a build agent, 2026-11-14). OWNER: build agent (Opus); review by the other model before Q-A relies on it.
WHAT: `.github/workflows/inspect.yml` (static aapt2 facts; optional API 35 x86_64 emulator with scripted taps; screenshots +
a contact sheet pushed to a `shots` branch; APK caching) and a `stub_kivymd/` test app with optional shadows-off / transition
flags. Spec: docs/inspect.md once committed.
ACCEPTANCE: one cold run of the stub completes; the summary prints COLD/WARM, image digest, host arch, pip versions, the
aapt2 facts (targetSdk, minSdk, ABIs, permissions) and the contact sheet link; docs/inspect.md matches the workflow inputs.
QUEUE NOTE: the flags Q-A and Q-B need (Fbo counter, transition choice, targetSdk, edge-to-edge opt-out, insets padding,
variant selector) are inputs or `extra` overrides, never one-off hard-coded copies (CLAUDE.md "Generic first").

## Q-A RUNNER INVESTIGATION
STATUS: BLOCKED on Q-0. OWNER: Opus subagent (dispatch + read); small stub patches by Opus, reviewed by Fable only if a
run's result would be posted. BUDGET: ~2 h of the author's / chats' time OR ~15 GitHub runs for Q-A + Q-B + Q-C together,
whichever comes first. Split: Q-A up to 10 runs, Q-B up to 3, Q-C up to 2. Over budget = stop and ask the author.
REALISTIC TIMING: a cold buildozer build is ~16-20 min plus ~5-10 min of emulator; a warm (`sdk`) run is ~4-8 min. Two cold
runs (first + final) + ~8 warm runs fits ~2 h of machine time only with caching; all-cold would be ~4-5 h.
RUNS (each: question / hypothesis / what would refute it):
- A-1 COLD BASELINE. Q: does the stub (shadows on, default MD transition, targetSdk 35) build, launch and switch screens on
  the API 35 emulator, and which GL renderer does it get? H: no crash; renderer = SwiftShader (or ANGLE over it); bars overlap
  the UI. Record GL_VENDOR / GL_RENDERER / GL_VERSION in the summary. Refuted if it crashes (then the bug is not Adreno-only:
  jump straight to bisecting on the runner with the Q-B variants).
- A-2 OVERLAP CONTROL. Q: is the overlap caused by targetSdk 35? H: same stub at targetSdk 34 shows no overlap.
- A-3 FIX 1, OPT-OUT. Q: does `windowOptOutEdgeToEdgeEnforcement=true` in the activity theme remove the overlap at targetSdk 35?
  H: yes. Note in the result: this opt-out is a stopgap; at targetSdk 36 Android ignores it, so it is not the long-term fix.
- A-4 FIX 2, INSETS. Q: does padding the root layout by the system-bar insets (read via pyjnius from the window insets)
  remove the overlap with edge-to-edge kept? H: yes, on both a portrait and a gesture-nav screenshot.
- A-5 FBO COUNT, SHADOWS ON. Q: do screen switches create BoxShadow Fbos? H: yes, Fbo creations logged per switch > 0 and
  scale with the number of elevated widgets on the incoming screen. Instrument in the stub only (count / log Fbo creation,
  e.g. wrap or subclass at the stub level; never patch Kivy itself for this).
- A-6 FBO COUNT, SHADOWS OFF. Q: does the count drop to ~0 with shadows off? H: yes. Together with A-5 this confirms the Fbo
  source on the software renderer (it says nothing about the driver crash itself).
- A-7 TRANSITION. Q: does a Kivy ShaderTransition (FadeTransition) add its own Fbo per switch, and the MD transition none?
  H: yes / none, matching the source reading.
- A-8 to A-10: RESERVE for re-runs and the FINAL COLD run that backs whatever is posted (overlap fix screenshots + Fbo counts).
ACCEPTANCE: every run above has a hand-back line (link, COLD/WARM, answer); the overlap fix is shown by cold-run
screenshots before / after; the Fbo counts on vs off are in one cold run's summary; GL_RENDERER is recorded. If A-1 shows a
software renderer and no crash, the item closes with "runner cannot see the driver crash, see Q-B".

## Q-B HARDWARE BISECTION KIT (5 tests for the crashing phone)
STATUS: BLOCKED on Q-0 (and on A-1's renderer line, which justifies it). OWNER: Fable builds (its result can only be
checked on the user's phone, never on the runner); Opus reviews before it is sent. BUDGET: up to 3 runs (one matrix build of
all 5, one fix-up, one final cold build that produces the APKs actually sent). DEPENDS: Q-0; Q-A A-5/A-6 instrumentation reused.
DESIGN RULES:
- Exactly 5 variants, BUILT ON GITHUB as release / artifact APKs for arm64-v8a (the phone's ABI), from ONE generator (the
  stub + a variant input), never 5 hand-written apps. Same Kivy / KivyMD / Python versions as the user's app; p4a branch =
  the one CLAUDE.md "Log" shows passing (develop as of 2026-11-12).
- Each variant opens on screen 1 with ONE big button "switch"; tapping it switches to screen 2 and back 20 times (auto-repeat
  after one tap), then shows "DONE". The user reports only CRASH (app closes / freezes) or NO CRASH (sees DONE).
- Ordered as a LADDER: each step adds exactly one factor to the one before. The FIRST step that crashes names the trigger;
  the user may stop at the first crash, but running all 5 makes the answer stronger.
THE 5 VARIANTS:
| # | Variant | Adds | CRASH means | NO CRASH means |
|---|---------|------|-------------|----------------|
| 1 | Plain Kivy ScreenManager, SlideTransition, plain buttons | baseline: screens, no Fbo | not Fbo-related: Kivy GL / the driver on any redraw; theory wrong | the plain switch path is safe |
| 2 | 1 + one raw Kivy `Fbo` widget drawn on screen 2 | a bare Fbo | any Fbo on screen change triggers it; not BoxShadow-specific | a lone Fbo is fine |
| 3 | 1 + three widgets with Kivy `BoxShadow` on screen 2 (no KivyMD) | BoxShadow (Fbo + shader) | BoxShadow is the trigger; KivyMD is innocent | BoxShadow alone is fine |
| 4 | KivyMD MDScreenManager, MDSharedAxisTransition, elevated cards with shadows OFF | KivyMD screens + its transition | KivyMD's transition / widgets trigger it without shadows | KivyMD without shadows is safe = workaround |
| 5 | 4 with shadows ON (stock elevation) | KivyMD elevation shadows | confirms the user's crash with the minimum app | crash needs something else in the user's app (ask for their KV) |
Reading: crash first at 3 (or 5 with 4 clean) = BoxShadow, the leading theory; workaround = shadows off / elevation 0 on
that phone. Crash first at 2 = any Fbo. Crash at 1 = not Fbo at all. No crash anywhere = the user's app has another factor.
(A Kivy ShaderTransition test was left out to keep exactly 5; it would sit between 2 and 3 if a 6th slot is ever allowed.)
RESULT TABLE (the user fills in; copy into the reply):
| # | Variant | CRASH / NO CRASH | Phone + Android version |
|---|---------|------------------|-------------------------|
| 1 | plain Kivy | | |
| 2 | raw Fbo | | |
| 3 | BoxShadow | | |
| 4 | KivyMD shadows off | | |
| 5 | KivyMD shadows on | | |
ACCEPTANCE: one cold matrix run produces 5 arm64 APKs whose aapt2 facts (package, versions, ABI, targetSdk) are in the
summary; each variant has a distinct package name so all 5 install side by side; each launches and completes its 20 switches
on the emulator (via Q-C if it works, else an x86_64 twin build) with no crash; Opus review signed off; the instructions to
the user are 5 numbered lines + the table, no jargon.

## Q-C ARM64 APK ON THE x86_64 EMULATOR (inspection, untested)
STATUS: READY to inspect after Q-0 (no build needed to start). OWNER: Opus subagent (inspection). BUDGET: up to 2 runs.
QUESTION: can the API 30+ x86_64 emulator image on the runner install and run an arm64-v8a-only Kivy APK through its ARM
translation layer? H: yes on the Google APIs images, slowly; unknown on the default image. If yes, Q-B's exact APKs are
smoke-tested as sent (no x86_64 twin builds).
ACCEPTANCE: one run installs a Q-B arm64 APK on the emulator and records install result, launch result, the image name, and
whether translation was used (from the device ABI list); or a written "does not work because ..." with the log line.
LIMIT (say it in the result): translation still renders with SwiftShader, so it cannot reproduce the Adreno crash either.

## Q-D LATER: KIVY HELP-REQUEST FEED (scope creep, NOT NOW)
STATUS: LATER, flagged as scope creep relative to the author's course deadline; raise again only after the course ships or
the author asks. OWNER: design by Opus when released.
WHAT: a feed of Kivy help requests (r/kivy RSS, Stack Overflow [kivy] tag RSS, the Kivy Google Group if it has a feed, kivy
GitHub issues) -> a human-reviewed digest -> the author dispatches inspect / build runs BY HAND.
HARD RULES: never auto-trigger a run from feed content (untrusted input; workflows interpolate inputs into shell); never
auto-post replies (spam / subreddit rules); always a human in the loop.

## Q-E DOCS NOTE (no item)
The reply draft to the user lives in the parent chat. Q-A and Q-B results feed back into it (overlap fix with screenshots,
the 5-test kit + table). Claims in it cite cold-run links only.

## DONE
(nothing yet)
