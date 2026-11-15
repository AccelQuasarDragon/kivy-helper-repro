# Discord cards: one rich embed per run

Discord shows GitHub's generic card for GitHub links and a bare image for a raw PNG. A **card page**
is a tiny static `index.html` with Open Graph / Twitter tags (`summary_large_image`), so the link
unfurls as ONE embed: title + one-line result + the big contact sheet.

## Generator
`tools/card_page.py` (stdlib) turns (title, description, image URLs, links) into a card page. Every
caller uses it. A **run card** is a card with one section; a **report card** is the same card with
one section per run (`--spec card.json`; og:image = the first section's sheet unless `image` is set;
report.yml adds `runs`, below).
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
-> Run workflow (workflow_dispatch only). ONE spec, three views in `shots/<slug>/`:
- `index.html`: the card page (og:image = `sheet.png`), one section per run + a link to TESTS.md;
- `TESTS.md`: the same spec as GitHub markdown: title, description, a table of every run (run + card
  links, question, result, cache, status, screenshot links), the extra sections;
- `sheet.png`: ONE contact sheet of the runs' screenshots, each tile labelled run label + file stem,
  a colour band per run (`tools/contact_sheet.py --groups`).

Inputs: `label` (run name); `slug` (`shots/<slug>/`: a letter, then `a-z 0-9 -`, 1-40 chars, so it
never matches an inspect run's all-digit folder; empty = `report-<run_id>`); `overwrite` (false =
refuse an existing folder, "NOT PUBLISHED"); `spec` (JSON, max 20000 chars):

    {"title": "KivyMD 2 on API 35", "description": "two causes, three runs",
     "runs": [{"id": 19412345678, "label": "cold, stock spec", "question": "does it start?",
               "result": "APP DIED", "cache": "cold", "status": "proven"},
              {"id": 19412349999, "label": "fix applied", "result": "APP OK", "cache": "warm",
               "images": ["launch.png", "tap1.png"]}],
     "sections": [{"heading": "notes", "text": "...", "links": [["docs", "https://github.com/..."]]}]}

`runs`: at most 20; `id` = an inspect run id (digits); `label` <= 40 chars; `question` / `result`
<= 400; `cache` = `cold|warm|apk`, `status` = `proven|inferred` (both optional); `images` = PNG names in
that run's `shots/<id>/` (max 12; default = its first 4 by name, `sheet.png` excluded). The sheet holds at
most 40 tiles (defaults are dealt round-robin, one per run first) at 480 px high, columns picked for a
roughly 16:9 image, and shrinks its tiles until the PNG is <= 8 MB. `sections` are optional extras (card
format above). A spec with no screenshots needs its own `image`. Run URLs are built from the ids; free text
is escaped (HTML; markdown incl. `|`, backticks, HTML, and bare URLs defused); only allowlisted https links.

Jobs: `render` (read-only: validates, sparse-checks-out `shots/<id>/` of the listed runs from branch
`shots` without credentials, renders the three files, uploads artifact `report-<n>-a<attempt>`) ->
`publish` (the ONLY job here with `contents: write`) pushes the folder with `tools/push_shots.sh` (the
same race-safe push as inspect's shots job). Its summary prints:
- card page (post it bare, as in "Posting in Discord"): `https://accelquasardragon.github.io/kivy-helper-repro/shots/<slug>/`
- `https://github.com/AccelQuasarDragon/kivy-helper-repro/blob/shots/shots/<slug>/TESTS.md`
- `https://accelquasardragon.github.io/kivy-helper-repro/shots/<slug>/sheet.png`

Preview locally (a `shots` checkout in `shotsrc/`):
`uv run --no-project tools/card_page.py index.html --spec report.json --repo OWNER/NAME --slug my-report --md TESTS.md --shots-root shotsrc --sheet-manifest m.json`
then `uv run --script tools/contact_sheet.py sheet.png --groups m.json --max-bytes 8000000`.
