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

## Run cards (automatic)
inspect.yml's `shots` job writes `shots/<run_id>/index.html` next to the PNGs. Title = the run's
`label`; description = `COLD|WARM run · APP ALIVE|APP DIED|... · targetSdk N · K screenshot(s)`
(fixed words from the inspect job, never log text). It adds an empty `.nojekyll` at the branch root
so Pages serves files as-is, and prints the page URL in the step log and the job summary.

**One-time setup (author):** Settings -> Pages -> Deploy from a branch -> `shots`, `/ (root)`.
A page appears about a minute after each push.

URL pattern: `https://accelquasardragon.github.io/kivy-helper-repro/shots/<run_id>/`
(runs before this feature have no `index.html`; their raw PNG links still work).

## Posting in Discord
- Post the Pages URL **bare** on its own: that link makes the card.
- Wrap every other link in `<...>` (e.g. `<https://github.com/...>`) to suppress its embed, or remove
  an unwanted embed with the X on your own message.
- Edit the label before dispatch: it is the card title everyone sees.

## Privacy
Pages publishes only what the public `shots` branch already holds (PNGs + this page). Still: look at
the screenshots before sharing, and never put a reporter's name in a `label` (it becomes the title).

## Report cards (not automated: needs the author's decision)
A report diagnosing several issues ends with one embed linking every run. The generator supports it:

    uv run --no-project tools/card_page.py index.html --spec report.json

`report.json`: `{"title", "description", "url", "sections": [{"heading", "text", "image", "page",
"images", "links": [[text, url]]}, ...]}`, one section per run (`text` = that run's one-liner,
`page` = its run card). Publishing it needs a write to `shots`; CLAUDE.md allows `contents: write`
only on inspect's `shots` job, so no workflow was built. Options:

- **(a)** a `report` input on inspect.yml (e.g. a list of run ids + title): the shots job reads each
  run's existing `index.html` / sheet from the `shots` branch and writes `shots/report-<id>/index.html`.
  Stays inside the one job allowed to write; mixes two purposes into one workflow.
- **(b)** a separate `report.yml` with its own `contents: write` job: cleaner, but needs a CLAUDE.md
  rule change first.
- **(c)** the author generates the HTML locally and commits it to `shots` by hand (no workflow,
  no permission change; manual steps each time).
