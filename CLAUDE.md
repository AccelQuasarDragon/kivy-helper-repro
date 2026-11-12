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
- Inputs are interpolated into shell: fine while only collaborators can dispatch; never add a
  trigger that untrusted users can fire (pull_request_target, issue_comment, ...).

## Cache protocol (author, 2026-11-12)
Caches hide bugs (run #1 reproduced a pip bug that lives in the project `.buildozer` build venv;
a restored cache would have masked it). Planned input `cache: off | sdk | full` (default `off`;
`sdk` = `~/.buildozer` only: SDK/NDK/p4a download; `full` = also the project `.buildozer`):
1. A NEW bug: first run cold (`off`).
2. Iterating after that: `sdk` (or `full` only if the bug is clearly not in the build dirs).
3. Final check before posting an answer anywhere: cold (`off`) again.
Only a cold run is evidence: "reproduced" / "fixed" claims cite a cold run's link, never a warm one.
Every summary must say which cache level ran and whether it was hit.

## Privacy check (before every push)
    git grep -nIiE '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|[A-Z]:\\|/Users/|/home/[a-z]|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_' -- . ':!CLAUDE.md'
    git log --all --format='%an <%ae> | %cn <%ce>' | sort -u   # only the GitHub noreply address
Expected: no hits except `/home/user` (the container's own user) and the noreply author.

## Log
- 2026-11-12: created; run #1 = pip `capture_logging` ImportError repro (kivy only, p4a master, x86).
