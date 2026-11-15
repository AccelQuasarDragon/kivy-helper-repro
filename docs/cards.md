# Discord cards: one rich embed per run

Discord shows GitHub's generic card for GitHub links and a bare image for a raw PNG. A **card page**
is a tiny static `index.html` with Open Graph / Twitter tags (`summary_large_image`), so the link
unfurls as ONE embed: title + one-line result + the big contact sheet.

## Generator
`tools/card_page.py` (stdlib) turns (title, description, image URLs, links) into a card page. Every
caller uses it. A **run card** is a card with one section; a **report card** is the same card with
one section per run (`--spec card.json`; og:image = the first section's sheet unless `image` is set).
Every text value is HTML-escaped; every URL must be https on `raw.githubusercontent.com`,
`github.com` or `accelquasardragon.github.io` (`--allow-host` adds one, e.g. a fork's Pages host).
The description is cut to 200 chars. See the docstring for the CLI and the JSON spec.
Bad input (a URL that is not plain https on an allowed host, incl. any explicit port; a spec that is
not valid JSON or has the wrong shape; a missing key) = one `card_page: ...` line on stderr, exit 2.
Callers pass free text in the `=` form (`--title="$LABEL"`), so a label like `--help` stays a value.

## Run cards (automatic)
inspect.yml's `shots` job writes `shots/<run_id>/index.html` next to the PNGs. Title = the run's
`label`; description = `<source> · <app state> · targetSdk N · K screenshot(s)`, fixed words from
the inspect job, never log text:
- source: `COLD run` (built, nothing restored from a cache), `WARM run` (built, a cache hit), or
  `APK input (no build)` (the APK came from `apk_url` or another run's artifact);
- app state: `APP OK` (alive at the end), `APP DIED`, `APP NOT INSTALLED`, `ADB LOST DEVICE`, `APP STATE UNKNOWN`,
  or `static only` (`static_only` run: no emulator);
- N = targetSdk from aapt2 (`?` when unreadable);
- a non-built APK adds a last piece: ` · from apk_url`, or ` · from run <id> artifact <name>`
  (validated digits / charset only), and an artifact card links the source run.
 It adds an empty `.nojekyll` at the branch root
so Pages serves files as-is, and prints the page URL in the step log and the job summary.

**One-time setup (author):** Settings -> Pages -> Deploy from a branch -> `shots`, `/ (root)`.
Pages deploys about a minute (sometimes more) after each push.

**Pruning:** `shots/` grows by one folder per inspect run, and a Pages site is limited to about 1 GB.
When it gets big, delete old `shots/<run_id>/` folders from the `shots` branch (their card pages
and raw PNG links stop working; the runs' artifacts expire after 14 days anyway).

URL pattern: `https://accelquasardragon.github.io/kivy-helper-repro/shots/<run_id>/`
(runs before this feature have no `index.html`; their raw PNG links still work).

## Posting in Discord
- Open the Pages URL in a browser FIRST and post it only once it loads (Pages needs ~1+ minute
  after the push). Posted too early, Discord caches an empty embed for that URL: post it again
  with `?1` appended (`.../shots/<run_id>/?1`; `?2` for a second retry), which Discord treats as a new link.
- Post the Pages URL **bare** on its own: that link makes the card.
- Wrap every other link in `<...>` (e.g. `<https://github.com/...>`) to suppress its embed, or remove
  an unwanted embed with the X on your own message.
- Edit the label before dispatch: it is the card title everyone sees.

## Privacy
Pages publishes only what the public `shots` branch already holds (PNGs + this page). Still: look at
the screenshots before sharing, and never put a reporter's name in a `label` (it becomes the title).

## Report cards: report.yml
A report diagnosing several issues ends with one embed linking every run. Actions tab -> "report card"
-> Run workflow (workflow_dispatch only):
- `label`: the run name;
- `spec`: the card JSON (max 20000 chars): `{"title", "description", "sections": [{"heading", "text",
  "image", "page", "images", "links": [[text, url]]}, ...]}`, one section per run (`text` = that run's
  one-liner, `image` = its `sheet.png` raw URL, `page` = its run card). `url` is set by the workflow to
  the report's own page; every other URL must pass card_page.py's allowlist (https on
  `raw.githubusercontent.com`, `github.com` or this repo's Pages host);
- `slug`: the folder, `shots/<slug>/` (a letter, then `a-z 0-9 -`, 1-40 chars, so it never matches an
  inspect run's all-digit `shots/<run_id>/`; empty = `report-<run_id>`);
- `overwrite`: false (default) refuses an existing `shots/<slug>/` (the run fails with "NOT PUBLISHED").

Jobs: `render` (read-only: validates, renders with `tools/card_page.py --spec`, uploads the HTML as
artifact `report-<n>-a<attempt>`) -> `publish` (the ONLY job here with `contents: write`) pushes
`shots/<slug>/index.html` with `tools/push_shots.sh`, the same race-safe push as inspect's shots job
(fresh fetch + commit per attempt, 10 jittered retries, no `concurrency:` group because GitHub cancels
older pending jobs of a group). Its summary prints
`https://accelquasardragon.github.io/kivy-helper-repro/shots/<slug>/`: post it as in "Posting in Discord"
(wait until it loads; `?1` to re-embed). Preview locally first:
`uv run --no-project tools/card_page.py index.html --spec report.json`.
