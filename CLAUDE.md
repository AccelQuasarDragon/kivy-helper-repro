# CLAUDE.md: kivy-helper-repro

PUBLIC REPO: everything here is world-readable. No local paths, usernames, emails, tokens, chat
links or names of the people whose reports we reproduce. Run the privacy check below before every push.

## What this is
A generator for buildozer build reproductions: a few form inputs -> a buildozer.spec -> a build on
GitHub Actions -> a log + summary. It replaces building other people's projects locally.
One reusable workflow, not one repo per question.

## Files
- `.github/workflows/build.yml`: the whole pipeline (workflow_dispatch form). Steps: free disk,
  pull image + record digest, `buildozer init` in the image + overrides, build, summary, artifact.
- `tools/patch_spec.py`: stdlib-only `key=value` overrides for a spec (replace in place, else append
  to [app]). Local run: `uv run --no-project tools/patch_spec.py SPEC 'k=v;k2=v2'`.
- `stub/main.py`: minimal Kivy app the builds compile.
- `.github/workflows/inspect.yml` + `docs/inspect.md` (READ IT before using or changing inspect): APK static
  facts + optional x86_64 emulator run (taps, screenshots, our runner's logcat); builds via build.yml
  (`workflow_call`); screenshots go to the orphan branch `shots`. Helpers: `tools/apk_pkgs.py`,
  `tools/emu_run.sh`, `tools/contact_sheet.py`. Test app: `stub_kivymd/` (+ its `spec_overrides.txt`).
- `QUEUE.md`: the DETAIL SPEC of planned items (runs, hypotheses, acceptance). SUPERSEDED for status (author,
  2026-11-14): status, order and done-ness live in the author's private task tracker (lane "kivy help"); never track
  status in QUEUE.md.

## How to run a repro
Actions tab -> "buildozer repro" -> Run workflow. Or via the API (workflow_dispatch on `build.yml`,
ref `main`, `inputs` as in the form). Put the question in `label`; it becomes the run name.
Read the run's Summary page first (host arch, image digest, pip versions, lines before the first error);
`build.log` is in the artifact.

## Design rules
- Generic first: new needs become form inputs or `extra` overrides, never a hard-coded one-off spec.
- Every run must record what it ran on (image digest, host arch, pip versions) so logs are comparable.
- A run does NOT match a reporter's stale `.buildozer` / `~/.buildozer` or rootless podman details;
  say so when reporting results.
- Inputs reach the shell ONLY through `env:` variables (never `${{ inputs.x }}` inside `run:`; since
  2026-11-14, inputs will come from Discord/Reddit reports); never add a trigger that untrusted users can
  fire (pull_request_target, issue_comment, ...). `contents: write` only on inspect's `shots` job.

## Cache protocol (author, 2026-11-12)
Caches hide bugs (run #1 reproduced a pip bug that lives in the project `.buildozer` build venv;
a restored cache would have masked it). Input `cache: off | sdk | full` (default `off`;
`sdk` = `~/.buildozer` only: SDK/NDK; `full` = also the project `.buildozer`: p4a checkout,
compiled recipes, build venv). Exact keys only (image digest + inputs + runner arch), no restore-keys;
`sdk` saves even on failure, `full` saves only on success. The run summary prints COLD/WARM:
1. A NEW bug: first run cold (`off`).
2. Iterating after that: `sdk` (or `full` only if the bug is clearly not in the build dirs).
3. Final check before posting an answer anywhere: cold (`off`) again.
Only a cold run is evidence: "reproduced" / "fixed" claims cite a cold run's link, never a warm one.
Every summary must say which cache level ran and whether it was hit.

## Privacy check (before every push)
    git grep -nIiE '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|[A-Z]:\\|/Users/|/home/[a-z]|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_' -- . ':!CLAUDE.md'
    git log --all --format='%an <%ae> | %cn <%ce>' | sort -u   # only the GitHub noreply address
Expected: no hits except `/home/user` (the container's own user) and the noreply author.
(A local fetch of the `shots` branch also shows the github-actions[bot] noreply address: expected.)

## Log
- 2026-11-12: created; run #1 = pip `capture_logging` ImportError repro (kivy only, p4a master, x86).
- 2026-11-12 results (all cold, ghcr.io/kivy/buildozer:latest, x86):
  - #1 master, 2 archs: FAIL `capture_logging`. Arch 1 ok (venv pip 25.3 -> 26.3); arch 2 reruns
    `python -m venv venv` on the same venv, then `pip install -U pip` crashes on mixed pip files.
    NOT reporter stale state: clean runner. Did not reproduce on Windows (venv rerun kept pip 26.3 intact),
    so the file-mixing step is Linux/container-specific, mechanism unconfirmed.
  - #2 master, arm64 only: no capture_logging; FAILS later on the known charset-normalizer cp314 android wheel bug.
  - #3 develop, 2 archs (api 36, ndk 29): PASS = the fix to recommend.
  - #4 cache test (arm64, master): failed (charset bug), so nothing saved; redone on develop.
  - #5 master, arm64 + `charset-normalizer==2.1.1`: FAIL, same charset wheel error; p4a's resolver adds a direct
    URL to the 3.5.2 android wheel that overrides the pin. No simple master workaround: answer = develop.
  - #6 cache test 1/2 (develop, arm64, full): build PASS, sdk + full caches saved (~1.7 GB each); Summary step
    crashed (grep no-match under pipefail), fixed.
  - #7 cache test 2/2 (same inputs as #6): both caches HIT (16 s restore each), build 63 s vs ~16 min cold,
    saves skipped, Summary ok. Warm runs: ~4 min total. Cache input verified end to end.
- 2026-11-12: release request posted upstream: kivy/python-for-android#3411 (cites runs #1, #2, #3, #5 + runs/
  excerpts at commit 50bea6c: keep runs/ files unchanged so the line links stay valid). Related: #3364, #3366.
- 2026-11-14: inspect.yml added (author-approved spec); build.yml became reusable (workflow_call) with
  repo/ref/app/add_archs/app_config/apk_cache inputs, all inputs via env. stub_kivymd checked on desktop only.
  Runs: none yet (no gh CLI on the build machine; dispatch pending).
