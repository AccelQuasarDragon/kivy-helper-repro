"""Generate a static HTML card page (Open Graph + Twitter tags) so a link pasted in Discord
unfurls as a rich embed: title + description + one big image. Stdlib only.

One spec, several views (docs/cards.md):
- run card: one section (a run's title, one-line result, contact sheet, per-PNG images, links)
- report card: several sections and/or a `runs` list; `runs` (the base data) generate the run
  sections of index.html, the table of TESTS.md (--md), the contact-sheet manifest
  (--sheet-manifest, for contact_sheet.py --groups), the highlights manifest (--embed-manifest,
  from `embed`) and the "How to recreate" section (from each run's inputs.json, else spec fields)

Every HTML text value is html.escape'd (quote=True); every markdown text value goes through md()
(markdown + HTML escaped, autolinks defused); every URL must be https on an allowed host.
Code (summary `code`, section `diagram`) is never free text: it sits escaped in <pre> / in a fence.
Every page carries a Content-Security-Policy meta: no script at all, or (a page with a diagram) only
the pinned, SRI-checked Mermaid file + its inline init (MERMAID_* below).
The og:description is cut to 200 chars (Discord truncates longer ones anyway); over 180 chars
prints a `warning:` line (report.yml copies it to its summary).

CLI (run card):
  card_page.py OUT.html --title T --description D --image SHEET_URL --url PAGE_URL \
      [--img PNG_URL ...] [--link 'text=URL' ...] [--allow-host HOST ...]
CLI (any card, incl. a report) from a JSON spec:
  card_page.py OUT.html --spec card.json [--allow-host HOST ...]
      [--repo OWNER/NAME --slug SLUG [--shots-root DIR] [--md TESTS.md] [--sheet-manifest M.json]
       [--embed-manifest E.json]]
  card_page.py --spec card.json --run-ids [--media-plan P.json]
      (validate only; print the runs' ids, one per line; P.json = the cleared phone media plan)
  spec = {"title", "description", "image", "url",
          "summary": {"bug": "...", "fix": "...", "code": "multi-line code example", "lang": "python",
                      "proof": "lead-in text", "proof_runs": [123, ...], "proof_links": [[text, url], ...]},
          "key_points": ["most important fact", ...],
          "sections": [{"heading", "text" (a newline = a new paragraph; '- x' / 'N. x' lines = lists), "diagram": "flowchart TD ...", "image", "images": [...],
                        "links": [[text, url], ...], "page": url}],
          "runs": [{"id": 123, "label", "question", "result", "learned", "cache": "cold|warm|apk",
                    "status": "proven|inferred", "images": ["launch.png", ...],
                    "settings": "short text", "recreate": {"input": "value", ...},
                    "workflow": "inspect.yml|build.yml|devicelab.yml (the form `recreate` fills; default inspect.yml)",
                    "media": {"cleared": true, "artifact": "devicelab-10-a1", "digest": "sha256:<64 hex>",
                              "images": "all" | ["3.png", ...], "video": true, "frames": 8, "replace": false}}],
          "embed": [{"run": 123, "image": "00_launch.png", "caption": "..."}]}
  runs -> ONE block per run (run_view; index.html and TESTS.md): label + verdict badge (verdict(): the first
    word of `result` directly followed by ':' or ',', CRASH / FAIL / FAILED = red, CLEAN / PASS = green, else none), a 2-column table
    (Result, What we learned = `learned`, Question, Where it ran (derived), Settings, Test Lab, Evidence, Links;
    empty rows skipped), then the run's video, frame strip and screenshots. Recreate steps stay at the bottom.
  summary = the author's 3 bullets ABOVE the title: (1) bug, (2) fix + code example (escaped <pre>, a
    fence in TESTS.md), (3) proof = links to runs (proof_runs: ids from `runs`) and/or allowlisted URLs;
    bug, fix and at least one proof link required. key_points stay right under the title.
  diagram = a Mermaid flowchart (validate_diagram: first line flowchart|graph + direction; no click / href /
    call, URLs, script: / data: URLs, HTML tags except <br/>, %%{ directives, backticks, @{, url(, &#;
    <= DIAGRAM_MAX chars): index.html renders it with the pinned Mermaid (strict), TESTS.md as a fence.
  media = devicelab.yml (phone) runs only: report.yml's media job copies the run's screenshots / video /
    frames into shots/<id>/ (tools/devicelab_media.py) ONLY when "cleared" is literally true (the operator
    looked at every image and the video first) and from exactly the named `artifact` whose zip matches
    `digest` (the bytes that were eye-checked); any other media value refuses the spec. An already
    published shots/<id>/ is kept (the report uses it) unless "replace": true. A folder with
    devicelab.json shows ALL its screenshots, a frame strip, the video and run facts; its PNGs work in
    `images` and `embed` like any run's. Later reports reuse a published folder without `media`.
  With --repo/--slug, "url" = the Pages page of shots/<slug>/ and run URLs are built from the ids.
  --shots-root = a checkout of branch `shots`: each run's PNGs are picked from DIR/shots/<id>/
  (its `images`, else the first PER_RUN_DEFAULT; at most SHEET_MAX tiles in all); when any PNG is
  picked, og:image = shots/<slug>/sheet.png (render it from --sheet-manifest). Each run's
  DIR/shots/<id>/inputs.json (written by inspect.yml's shots job) gives its settings + recreate steps.
  A run's card page (shots/<id>/) is linked ONLY when DIR/shots/<id>/index.html exists (no dead links;
  without --shots-root nothing is linked).
  With `embed` and --embed-manifest: og:image = shots/<slug>/embed.png instead (a highlights sheet,
  contact_sheet.py --groups E.json --height 900 --font-size 36); the full sheet stays on the page.
Locally: uv run --no-project tools/card_page.py ...
Exit codes: 0 written, 2 bad input (bad URL, malformed spec, missing key); argparse errors are 2 too.
Pass free text in the `=` form (--title="$LABEL") so a value like `--help` is not read as an option.
"""
import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
from urllib.parse import urlsplit

ALLOWED_HOSTS = ('raw.githubusercontent.com', 'github.com', 'accelquasardragon.github.io')
DESC_MAX, DESC_WARN = 200, 180
THEME = '#2b6cb0'
# spec shape limits (the workflow also caps the spec at 20000 chars)
RUNS_MAX, SECTIONS_MAX, LABEL_MAX, TEXT_MAX, IMAGES_MAX = 20, 30, 40, 400, 12
KEY_POINTS_MAX, EMBED_MAX, CAPTION_MAX, SETTINGS_MAX, VALUE_MAX = 10, 6, 80, 300, 2000
# contact sheet caps: tiles per run when `images` is omitted, tiles in all
PER_RUN_DEFAULT, SHEET_MAX = 4, 40
CACHES, STATUSES = ('cold', 'warm', 'apk'), ('proven', 'inferred')
RUN_ID = re.compile(r'[1-9][0-9]{0,19}')
PNG = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.png')
REPO = re.compile(r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}')
SLUG = re.compile(r'[a-z][a-z0-9-]{0,39}')
MD_URL = re.compile(r"[A-Za-z0-9._~:/?#@!$&'*+,;=%-]+")
INPUT_KEY = re.compile(r'[a-z][a-z0-9_]{0,29}')
HEX = re.compile(r'[0-9a-f]{7,40}')
TRUNC_MARK = '…truncated'  # end of an inputs.json value cut at VALUE_MAX (never sent as a recreate value)
WORKFLOW = re.compile(r'[a-z][a-z0-9_-]{0,40}\.yml')
WORKFLOWS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, '.github', 'workflows')
RECREATE_WORKFLOWS = ('inspect.yml', 'build.yml', 'devicelab.yml')  # workflows whose form a recreate section can fill
_FORMS = {}
# Mermaid diagrams (section `diagram`): index.html loads ONE pinned file from jsdelivr with its SRI hash
# (sha384 of the exact file, identical on unpkg; checked 2026-11-18: a self-contained IIFE, no dynamic
# import, no eval / new Function) and renders with securityLevel 'strict'; a CSP meta allows only that
# file + the inline init (by hash). TESTS.md uses a ```mermaid fence (GitHub renders it, sandboxed).
MERMAID_VERSION = '12.2.0'
MERMAID_URL = f'https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js'
MERMAID_SRI = 'sha384-8xUhuLNMjW/cI2Dacg3DR4WliYznvIg0LVG1stctThKD/YVrJFI9TNCFxft5NYgp'
MERMAID_INIT = "mermaid.initialize({startOnLoad:true,securityLevel:'strict',theme:'dark'});"
DIAGRAM_MAX, DIAGRAM_LINES = 6000, 200
DIAGRAM_FIRST = re.compile(r'(flowchart|graph)[ \t]+(TD|TB|BT|LR|RL)[ \t]*')
DIAGRAM_STYLE = re.compile(r'\s*(classDef|style|linkStyle)\s')
DIAGRAM_HEX = re.compile(r'#[0-9A-Fa-f]{3,8}(?![0-9A-Za-z_])')
DIAGRAM_BR = re.compile(r'(?i)<br[ \t]*/?>')  # the ONE tag allowed (line break in a label)
DIAGRAM_BAD = [  # (pattern, reason): anything that could link, run code, fetch or reconfigure
    (re.compile(r'(?i)\b(click|href|call)\b'), 'click / href / call (links and callbacks)'),
    (re.compile(r'%%\{'), '%%{ init directive (config override)'),
    (re.compile(r'(?i)(java|vb)script\s*:'), 'script: URL'),
    (re.compile(r'(?i)\bdata\s*:\s*[a-z]+/'), 'data: URL'),
    (re.compile(r'(?i)[a-z][a-z0-9+.-]*://|\bwww\.'), 'URL'),
    (re.compile(r'<[A-Za-z/!?]'), 'HTML tag (only <br/> is allowed)'),
    (re.compile(r'`'), 'backtick (markdown strings)'),
    (re.compile(r'@\{'), '@{ node shape / image syntax'),
    (re.compile(r'(?i)url\s*\('), 'url( in a style'),
    (re.compile(r'&#|\\u'), r'encoded character (&# or \u)'),
    (re.compile(r'#\w+;'), 'Mermaid entity code (#name; / #123;)'),
    (re.compile(r'//'), 'protocol-relative URL (//host)'),
    (re.compile(r'[\x00-\x08\x0b-\x1f\x7f]'), 'control character'),
]
# report summary (spec `summary`, rendered ABOVE the title): bug, fix + code example, proof links
SUMMARY_TEXT, SUMMARY_CODE, SUMMARY_LINKS = 600, 3000, 8
CODE_LANG = re.compile(r'[a-z0-9]{1,15}')
# devicelab media (run `media`, copied into shots/<id>/ by tools/devicelab_media.py; read back from
# shots/<id>/devicelab.json). Publishing images / video is an explicit per-run opt-in: cleared = true.
MEDIA_IMAGES_MAX, MEDIA_FRAMES_MAX, MEDIA_FRAMES_DEFAULT = 40, 12, 8
VIDEO_NAME = 'video.mp4'
MEDIA_ARTIFACT = re.compile(r'devicelab-[0-9]{1,10}-a[0-9]{1,4}')
MEDIA_DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
FACT = re.compile(r"[A-Za-z0-9 ,.()_:'/-]{0,80}")


def workflow_form(wf: str) -> tuple:
    """(display name, {input: form default} in form order) of a workflow's workflow_dispatch form,
    READ FROM THE WORKFLOW FILE (no hand-kept copy that could drift). A targeted parse of this repo's
    own style: `name:` at the top; under `workflow_dispatch:` -> `inputs:`, each input at 6 spaces and
    its `default:` at 8 spaces (quoted 'x' / "x" or a bare word). Missing file = ('', {})."""
    if wf in _FORMS:
        return _FORMS[wf]
    name, form, state, cur = '', {}, 0, None
    try:
        with open(os.path.join(WORKFLOWS_DIR, wf), encoding='utf-8') as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        m = re.fullmatch(r'name:\s*(.+?)\s*', line)
        if m and not name:
            name = _unquote(m[1])
        if state == 0 and line.rstrip() == '  workflow_dispatch:':
            state = 1
        elif state == 1 and line.rstrip() == '    inputs:':
            state = 2
        elif state == 2:
            if line.strip() and len(line) - len(line.lstrip(' ')) < 6:
                break  # end of the inputs block
            m = re.fullmatch(r' {6}([a-z][a-z0-9_]*):\s*', line)
            if m:
                cur = m[1]
                form[cur] = ''
                continue
            m = re.fullmatch(r' {8}default:\s*(.*?)\s*', line)
            if m and cur:
                form[cur] = _unquote(m[1])
    _FORMS[wf] = (name, form)
    return _FORMS[wf]


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1]
    return v


def check_url(url: str, hosts) -> str:
    """Return url if it is https on an allowed host, else raise ValueError."""
    if not isinstance(url, str) or any(c.isspace() for c in url):
        raise ValueError(f'bad URL: {url!r}')
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.username or parts.password or parts.port is not None:
        raise ValueError(f'URL must be plain https: {url!r}')
    if (parts.hostname or '').lower() not in hosts:
        raise ValueError(f'host not allowed: {parts.hostname!r} (allowed: {", ".join(hosts)})')
    return url


def short(text: str, n: int = DESC_MAX) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= n else text[:n - 1].rstrip() + '…'


MD_PUNCT = set('\\`*_{}[]()#+-.!|~$')  # `$`: GitHub renders $...$ as math
ZWSP = '​'


def md(text, n: int = 0) -> str:
    """Free text -> inert one-line GitHub markdown: HTML special chars as entities, markdown
    punctuation (incl. `|`, `$` and backticks) backslash-escaped, and GFM autolinks defused (a zero-width
    space after every ':' and '@' and inside 'www.'), so only links we emit ourselves are links."""
    text = short(text, n) if n else ' '.join(str(text).split())
    ent = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}
    out = ''.join(ent.get(c) or ('\\' + c if c in MD_PUNCT else c) for c in text)
    out = out.replace(':', ':' + ZWSP).replace('@', '@' + ZWSP)
    return re.sub(r'(?i)(www)(?=\\\.)', r'\1' + ZWSP, out)


UL_ITEM = re.compile(r'- (.*\S.*)')
OL_ITEM = re.compile(r'([0-9]{1,9})\. (.*\S.*)')


def blocks(text) -> list:
    """Free text -> [('p', 0, line) | ('ul', 1, [items]) | ('ol', start, [items])]: a newline starts a new
    paragraph; in MULTI-line text, consecutive '- x' lines are one bulleted list and consecutive
    'N. x' lines one numbered list (starting at the first N). Single-line text is always one paragraph.
    Plain data: each renderer escapes every line / item on its own."""
    lines = [x for x in str(text).splitlines() if x.strip()]
    out = []
    for line in lines:
        m = (UL_ITEM.fullmatch(line) or OL_ITEM.fullmatch(line)) if len(lines) > 1 else None
        kind = None if not m else 'ul' if m.re is UL_ITEM else 'ol'
        if not kind:
            out.append(('p', 0, line))
        elif out and out[-1][0] == kind:
            out[-1][2].append(m[m.re.groups])
        else:
            out.append((kind, int(m[1]) if kind == 'ol' else 1, [m[m.re.groups]]))
    return out


def html_blocks(text, e) -> list:
    """blocks() -> HTML lines, every line / item through e()."""
    out = []
    for kind, start, body in blocks(text):
        if kind == 'p':
            out.append(f'<p>{e(body)}</p>')
        else:
            attr = f' start="{start}"' if kind == 'ol' and start != 1 else ''
            out.append(f'<{kind}{attr}>' + ''.join(f'<li>{e(x)}</li>' for x in body) + f'</{kind}>')
    return out


def md_blocks(text) -> list:
    """blocks() -> TESTS.md lines (a blank line after each paragraph / list), every line / item through md()."""
    out = []
    for kind, start, body in blocks(text):
        if kind == 'p':
            out += [md(body), '']
        else:
            out += [f'- {md(x)}' if kind == 'ul' else f'{start + k}. {md(x)}' for k, x in enumerate(body)] + ['']
    return out


def _text(v, name: str, n: int) -> str:
    if v is None:
        return ''
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise ValueError(f'{name} must be text')
    if len(str(v)) > n:
        raise ValueError(f'{name} is {len(str(v))} chars (max {n})')
    return str(v)


def _str_list(v, name: str, n_items: int, n_chars: int) -> list:
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > n_items:
        raise ValueError(f'{name} must be a list of at most {n_items}')
    return [_text(x, f'{name} item', n_chars) if isinstance(x, str) else _bad(f'{name} items must be text') for x in v]


def _bad(msg):
    raise ValueError(msg)


def _inputs(v, name: str, truncate: bool = False) -> dict:
    """A {input: value} object (recreate / inputs.json) -> {str: str}; values text, bool or number.
    truncate (inputs.json, written by a run): a value over VALUE_MAX is cut and marked, not refused."""
    if not isinstance(v, dict) or len(v) > 40:
        raise ValueError(f'{name} must be an object of at most 40 inputs')
    out = {}
    for k, x in v.items():
        if not isinstance(k, str) or not INPUT_KEY.fullmatch(k):
            raise ValueError(f'{name}: bad input name {k!r}')
        if isinstance(x, bool):
            x = 'true' if x else 'false'
        if truncate and isinstance(x, str) and len(x) > VALUE_MAX:
            x = x[:VALUE_MAX - len(TRUNC_MARK)] + TRUNC_MARK
        out[k] = _text(x, f'{name}.{k}', VALUE_MAX)
    return out


def validate_diagram(text, name: str = 'diagram') -> str:
    """A Mermaid flowchart source -> itself, or ValueError. Only `flowchart` / `graph` diagrams; nothing
    that can link (click / href / call, URLs), run or reference code (script: / data: URLs, HTML tags
    except <br/>, encoded characters), reconfigure the renderer (%%{ init }%%) or fetch (url(, @{ img });
    at most DIAGRAM_MAX chars / DIAGRAM_LINES lines. The renderers escape it too (HTML) or fence it (md)."""
    if not isinstance(text, str):
        raise ValueError(f'{name} must be text')
    if len(text) > DIAGRAM_MAX or text.count('\n') >= DIAGRAM_LINES:
        raise ValueError(f'{name}: at most {DIAGRAM_MAX} chars and {DIAGRAM_LINES} lines')
    text = text.replace('\r\n', '\n').replace('\t', '  ')
    lines = [x for x in text.split('\n') if x.strip()]
    if not lines or not DIAGRAM_FIRST.fullmatch(lines[0].strip()):
        raise ValueError(f'{name}: the first line must be "flowchart TD" / "graph LR" (TD TB BT LR RL)')
    rest = DIAGRAM_BR.sub(' ', text)
    # a hex colour (#888 / #2b6cb0) is CSS only on a style line; anywhere else `#...;` is an entity code
    rest = '\n'.join(DIAGRAM_HEX.sub(' ', x) if DIAGRAM_STYLE.match(x) else x for x in rest.split('\n'))
    for pat, why in DIAGRAM_BAD:
        if pat.search(rest):
            raise ValueError(f'{name}: not allowed: {why}')
    return text.strip('\n')


def validate_summary(card: dict, run_ids) -> dict | None:
    """spec `summary` -> {bug, fix, code, lang, proof, proof_runs, proof_links} or None.
    The author's top-of-report form: (1) the bug, (2) the fix with a code example, (3) the proof as
    links to the run(s) (`proof_runs`: ids from `runs`; `proof_links`: [text, url] pairs, allowlisted
    at render). bug, fix and at least one proof link are required."""
    sm = card.get('summary')
    if sm is None:
        return None
    if not isinstance(sm, dict):
        raise ValueError('summary must be an object {bug, fix, code, lang, proof, proof_runs, proof_links}')
    unknown = set(sm) - {'bug', 'fix', 'code', 'lang', 'proof', 'proof_runs', 'proof_links'}
    if unknown:
        raise ValueError(f'summary: unknown key(s) {", ".join(sorted(map(str, unknown)))}')
    out = {k: _text(sm.get(k), f'summary {k}', SUMMARY_TEXT) for k in ('bug', 'fix', 'proof')}
    if not out['bug'].strip() or not out['fix'].strip():
        raise ValueError('summary needs bug and fix')
    code = sm.get('code')
    if code is not None and not isinstance(code, str):
        raise ValueError('summary code must be text')
    out['code'] = (code or '').replace('\r\n', '\n').strip('\n')
    if len(out['code']) > SUMMARY_CODE:
        raise ValueError(f'summary code is {len(out["code"])} chars (max {SUMMARY_CODE})')
    out['lang'] = _text(sm.get('lang'), 'summary lang', 15)
    if out['lang'] and not CODE_LANG.fullmatch(out['lang']):
        raise ValueError('summary lang: a-z 0-9, up to 15 chars (e.g. python)')
    pr = sm.get('proof_runs') or []
    if not isinstance(pr, list) or len(pr) > SUMMARY_LINKS:
        raise ValueError(f'summary proof_runs must be a list of at most {SUMMARY_LINKS} run ids')
    out['proof_runs'] = []
    for x in pr:
        if isinstance(x, bool) or str(x) not in run_ids:
            raise ValueError(f'summary proof_runs: {x!r} is not in runs')
        out['proof_runs'].append(str(x))
    links = sm.get('proof_links') or []
    if not isinstance(links, list) or len(links) > SUMMARY_LINKS or not all(
            isinstance(li, (list, tuple)) and len(li) == 2 and all(isinstance(x, str) for x in li) for li in links):
        raise ValueError(f'summary proof_links must be a list of at most {SUMMARY_LINKS} [text, url] pairs')
    for t, _ in links:
        _text(t, 'summary proof_links text', LABEL_MAX * 2)
    out['proof_links'] = [list(li) for li in links]
    if not out['proof_runs'] and not out['proof_links']:
        raise ValueError('summary needs proof: at least one proof_runs id or proof_links pair')
    return out


def _media(v, rid: str) -> dict:
    """run `media` -> {artifact, digest, images: 'all' | [names], video: bool, frames: int, replace: bool}.
    Images / video cannot be scanned automatically, so `cleared` must be literally true: the operator looked
    at every image and the video OF THAT ARTIFACT first, and `artifact` + `digest` (the artifacts API's
    sha256 of its zip) pin exactly those bytes (docs/devicelab.md "Publishing phone media"). Anything else
    refuses the report. `replace`: true = replace an already published shots/<id>/ (default: keep it)."""
    if not isinstance(v, dict):
        raise ValueError(f'run {rid} media must be an object {{cleared, artifact, digest, images, video, frames, replace}}')
    unknown = set(v) - {'cleared', 'artifact', 'digest', 'images', 'video', 'frames', 'replace'}
    if unknown:
        raise ValueError(f'run {rid} media: unknown key(s) {", ".join(sorted(map(str, unknown)))}')
    if v.get('cleared') is not True:
        raise ValueError(f'run {rid} media: refused: "cleared": true is missing (look at every image and the video first)')
    if not isinstance(v.get('artifact'), str) or not MEDIA_ARTIFACT.fullmatch(v['artifact']):
        raise ValueError(f'run {rid} media: "artifact" must name the eye-checked artifact, e.g. "devicelab-10-a1"')
    if not isinstance(v.get('digest'), str) or not MEDIA_DIGEST.fullmatch(v['digest']):
        raise ValueError(f'run {rid} media: "digest" must be that artifact\'s digest from the artifacts API ("sha256:<64 hex>")')
    if not isinstance(v.get('replace', False), bool):
        raise ValueError(f'run {rid} media replace must be true or false')
    imgs = v.get('images', 'all')
    if imgs != 'all' and (not isinstance(imgs, list) or len(imgs) > MEDIA_IMAGES_MAX or
                          not all(isinstance(i, str) and PNG.fullmatch(i) for i in imgs)):
        raise ValueError(f'run {rid} media images: "all" or a list of at most {MEDIA_IMAGES_MAX} PNG names (e.g. "3.png")')
    video = v.get('video', False)
    if not isinstance(video, bool):
        raise ValueError(f'run {rid} media video must be true or false')
    frames = v.get('frames', MEDIA_FRAMES_DEFAULT if video else 0)
    if isinstance(frames, bool) or not isinstance(frames, int) or not 0 <= frames <= MEDIA_FRAMES_MAX:
        raise ValueError(f'run {rid} media frames: 0-{MEDIA_FRAMES_MAX}')
    if frames and not video:
        raise ValueError(f'run {rid} media frames need "video": true (frames are sampled from the video)')
    if imgs != 'all' and not imgs and not video:
        raise ValueError(f'run {rid} media: nothing to publish (no images, no video)')
    return {'artifact': v['artifact'], 'digest': v['digest'], 'images': imgs if imgs == 'all' else list(dict.fromkeys(imgs)),
            'video': video, 'frames': frames, 'replace': v.get('replace', False)}


def validate_sections(card: dict) -> None:
    sections = card.get('sections') or []
    if not isinstance(sections, list) or len(sections) > SECTIONS_MAX:
        raise ValueError(f'sections must be a list of at most {SECTIONS_MAX}')
    for k, s in enumerate(sections, 1):
        if not isinstance(s, dict):
            raise ValueError('each section must be an object')
        for key in ('heading', 'text', 'image', 'page'):
            if s.get(key) is not None and not isinstance(s[key], str):
                raise ValueError(f'section {k} {key} must be text')
        _text(s.get('heading'), f'section {k} heading', 256)
        _text(s.get('text'), f'section {k} text', 4000)
        _str_list(s.get('images'), f'section {k} images', 40, 500)
        if s.get('diagram') is not None:
            validate_diagram(s['diagram'], f'section {k} diagram')
        links = s.get('links') or []
        if not isinstance(links, list) or len(links) > 40 or not all(
                isinstance(li, (list, tuple)) and len(li) == 2 and all(isinstance(x, str) for x in li) for li in links):
            raise ValueError(f'section {k} links must be a list of [text, url] pairs')


def validate(card: dict) -> list:
    """Check the spec's shape and sizes; return its runs normalized
    ({id, label, question, result, cache, status, images|None, settings, recreate|None})."""
    if not isinstance(card, dict):
        raise ValueError('spec must be a JSON object')
    _text(card.get('title'), 'title', 256)
    if not str(card.get('title') or '').strip():
        raise ValueError('title is required')
    _text(card.get('description'), 'description', 2000)
    _str_list(card.get('key_points'), 'key_points', KEY_POINTS_MAX, TEXT_MAX)
    validate_sections(card)
    runs = card.get('runs') or []
    if not isinstance(runs, list) or len(runs) > RUNS_MAX:
        raise ValueError(f'runs must be a list of at most {RUNS_MAX}')
    out, seen = [], set()
    for r in runs:
        if not isinstance(r, dict):
            raise ValueError('each run must be an object')
        rid = str(r.get('id', ''))
        if isinstance(r.get('id'), bool) or not RUN_ID.fullmatch(rid):
            raise ValueError(f'run id must be a numeric run ID: {r.get("id")!r}')
        if rid in seen:
            raise ValueError(f'run {rid} listed twice')
        seen.add(rid)
        n = {'id': rid, 'label': _text(r.get('label'), f'run {rid} label', LABEL_MAX) or f'run {rid}',
             'question': _text(r.get('question'), f'run {rid} question', TEXT_MAX),
             'result': _text(r.get('result'), f'run {rid} result', TEXT_MAX),
             'learned': _text(r.get('learned'), f'run {rid} learned', TEXT_MAX),
             'cache': _text(r.get('cache'), f'run {rid} cache', 10).lower(),
             'status': _text(r.get('status'), f'run {rid} status', 10).lower(), 'images': None,
             'settings': _text(r.get('settings'), f'run {rid} settings', SETTINGS_MAX),
             'recreate': _inputs(r['recreate'], f'run {rid} recreate') if r.get('recreate') is not None else None,
             'workflow': _text(r.get('workflow'), f'run {rid} workflow', 50) or 'inspect.yml'}
        if n['workflow'] not in RECREATE_WORKFLOWS:
            raise ValueError(f'run {rid} workflow must be one of {", ".join(RECREATE_WORKFLOWS)}')
        if n['cache'] and n['cache'] not in CACHES:
            raise ValueError(f'run {rid} cache must be one of {", ".join(CACHES)}')
        if n['status'] and n['status'] not in STATUSES:
            raise ValueError(f'run {rid} status must be one of {", ".join(STATUSES)}')
        n['media'] = _media(r['media'], rid) if r.get('media') is not None else None
        if r.get('images') is not None:
            imgs = r['images']
            if not isinstance(imgs, list) or len(imgs) > IMAGES_MAX or \
                    not all(isinstance(i, str) and PNG.fullmatch(i) for i in imgs):
                raise ValueError(f'run {rid} images: a list of at most {IMAGES_MAX} PNG file names (a-z 0-9 . _ -)')
            n['images'] = list(dict.fromkeys(imgs))
        out.append(n)
    embed = card.get('embed') or []
    if not isinstance(embed, list) or len(embed) > EMBED_MAX:
        raise ValueError(f'embed must be a list of at most {EMBED_MAX}')
    for e in embed:
        if not isinstance(e, dict):
            raise ValueError('each embed item must be an object {run, image, caption}')
        if str(e.get('run', '')) not in seen or isinstance(e.get('run'), bool):
            raise ValueError(f'embed run {e.get("run")!r} is not in runs')
        if not isinstance(e.get('image'), str) or not PNG.fullmatch(e['image']):
            raise ValueError(f'embed image must be a PNG file name: {e.get("image")!r}')
        _text(e.get('caption'), 'embed caption', CAPTION_MAX)
    validate_summary(card, seen)
    return out


def media_plan(runs: list, shots_root=None) -> tuple:
    """(plan, kept): plan = [{id, artifact, digest, images, video, frames, replace}] of the runs with cleared
    `media` (report.yml's media job input); kept = the ids left out because shots_root/shots/<id>/devicelab.json
    is already published and `replace` is not true (the report then shows the published files: a later,
    smaller media set never silently deletes an earlier report's video / PNGs)."""
    plan, kept = [], []
    for r in runs:
        if not r.get('media'):
            continue
        if shots_root and not r['media']['replace'] and \
                os.path.isfile(os.path.join(shots_root, 'shots', r['id'], 'devicelab.json')):
            kept.append(r['id'])
        else:
            plan.append(dict(r['media'], id=r['id']))
    return plan, kept


def pick_images(runs: list, shots_root: str) -> None:
    """Set run['picked'] = the PNG names of shots_root/shots/<id>/ that go on the sheet and pages:
    a run's listed `images` (each must exist), else up to PER_RUN_DEFAULT of its sorted PNGs
    (sheet.png and strip.png excluded; numbers in names sort as numbers: 2.png before 10.png), handed
    out round-robin so every run gets one before any gets more; at most SHEET_MAX in all."""
    avail = {}
    for r in runs:
        d = os.path.join(shots_root, 'shots', r['id'])
        names = sorted((f for f in os.listdir(d) if PNG.fullmatch(f) and f not in ('sheet.png', 'strip.png')),
                       key=natural) if os.path.isdir(d) else []
        avail[r['id']] = names
        if r['images'] is not None:
            missing = [i for i in r['images'] if i not in names]
            if missing:
                raise ValueError(f'run {r["id"]}: not in shots/{r["id"]}/: {", ".join(missing)}')
        r['picked'] = list(r['images'] or [])
    budget = SHEET_MAX - sum(len(r['picked']) for r in runs)
    if budget < 0:
        raise ValueError(f'{SHEET_MAX - budget} images listed (max {SHEET_MAX} on one sheet)')
    auto = [r for r in runs if r['images'] is None]
    for k in range(PER_RUN_DEFAULT):
        for r in auto:
            if budget and k < len(avail[r['id']]):
                r['picked'].append(avail[r['id']][k])
                budget -= 1


def natural(name: str) -> list:
    """Sort key: digit runs compare as numbers (Test Lab names its screenshots 0.png ... 16.png)."""
    return [(0, int(t), '') if t.isdigit() else (1, 0, t) for t in re.split(r'(\d+)', name) if t]


PHONE_FACTS = {  # devicelab.json `facts` key -> (kind, label); kind int / num / text (FACT charset)
    'device': ('text', 'device'), 'outcome': ('text', 'Test Lab outcome'), 'details': ('text', 'details'),
    'test_time_s': ('int', 'test time (s)'), 'screenshots': ('int', 'screenshots in the artifact'),
    'video_s': ('num', 'video (s)'), 'crash_files': ('int', 'crash report files'), 'taps': ('int', 'scripted taps')}


def load_folders(runs: list, shots_root) -> None:
    """Per run, from shots_root/shots/<id>/ (a checkout of branch shots; absent = nothing):
    run['has_page'] = its index.html exists (a run card page: only then is it linked, no dead links);
    run['phone'] = its devicelab.json (written by tools/devicelab_media.py for cleared phone media):
    {images, frames, video, strip, sheet, facts, notes}, every name checked and present in the folder."""
    for r in runs:
        r['has_page'], r['phone'] = False, None
        if not shots_root:
            continue
        d = os.path.join(shots_root, 'shots', r['id'])
        r['has_page'] = os.path.isfile(os.path.join(d, 'index.html'))
        path = os.path.join(d, 'devicelab.json')
        if not os.path.isfile(path):
            continue
        with open(path, encoding='utf-8') as f:
            rec = json.load(f)
        where = f'shots/{r["id"]}/devicelab.json'
        if not isinstance(rec, dict) or rec.get('workflow') != 'devicelab.yml' or str(rec.get('run_id')) != r['id']:
            raise ValueError(f'{where}: want {{"workflow": "devicelab.yml", "run_id": "{r["id"]}", ...}}')

        def names(key, n):
            v = rec.get(key) or []
            if not isinstance(v, list) or len(v) > n or not all(isinstance(x, str) and PNG.fullmatch(x) for x in v):
                raise ValueError(f'{where}: {key} must be a list of at most {n} PNG names')
            return v

        def one(key, want):
            v = rec.get(key)
            if v is None:
                return None
            if not isinstance(v, str) or not want(v):
                raise ValueError(f'{where}: bad {key}: {v!r}')
            return v
        ph = {'images': names('images', MEDIA_IMAGES_MAX), 'frames': names('frames', MEDIA_FRAMES_MAX),
              'video': one('video', lambda v: v == VIDEO_NAME), 'strip': one('strip', lambda v: v == 'strip.png'),
              'sheet': one('sheet', lambda v: v == 'sheet.png'), 'facts': {},
              'notes': _str_list(rec.get('notes'), f'{where} notes', 10, 200)}
        for x in ph['images'] + ph['frames'] + [ph[k] for k in ('video', 'strip', 'sheet') if ph[k]]:
            if not os.path.isfile(os.path.join(d, x)):
                raise ValueError(f'{where}: lists {x}, which is not in the folder')
        facts = rec.get('facts') or {}
        if not isinstance(facts, dict):
            raise ValueError(f'{where}: facts must be an object')
        for k, v in facts.items():
            kind = PHONE_FACTS.get(k, (None,))[0]
            ok = (kind == 'text' and isinstance(v, str) and FACT.fullmatch(v)) or \
                 (kind == 'int' and isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10 ** 6) or \
                 (kind == 'num' and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < 10 ** 6)
            if not ok:
                raise ValueError(f'{where}: bad fact {k!r}')
            ph['facts'][k] = v
        r['phone'] = ph


def phone_line(r: dict) -> str:
    """One plain line of a phone run's facts (from devicelab.json), '' when none."""
    f = (r.get('phone') or {}).get('facts') or {}
    parts = []
    if f.get('device'):
        parts.append(f'device {f["device"]}')
    if f.get('outcome'):
        parts.append(f'Test Lab outcome {f["outcome"]}' + (f' ({f["details"]})' if re.search('[A-Za-z]', f.get('details') or '') else ''))
    if 'test_time_s' in f:
        parts.append(f'test time {f["test_time_s"]} s')
    if 'screenshots' in f:
        parts.append(f'{f["screenshots"]} screenshot(s)')
    if 'video_s' in f:
        parts.append(f'video {round(f["video_s"])} s')
    if 'crash_files' in f:
        parts.append(f'{f["crash_files"]} crash report file(s)')
    if 'taps' in f:
        parts.append(f'{f["taps"]} scripted tap(s)')
    return ('Phone run (Firebase Test Lab): ' + ' · '.join(parts)) if parts else ''


def load_inputs(runs: list, shots_root) -> None:
    """Set run['inputs'] (dispatch inputs, {name: text}) and run['inputs_src']:
    'run' = shots_root/shots/<id>/inputs.json (recorded by the run itself), else 'spec' = the
    spec's `recreate`, else None. A malformed inputs.json is an error (it is our own file)."""
    for r in runs:
        r['inputs'], r['inputs_src'] = None, None
        path = os.path.join(shots_root, 'shots', r['id'], 'inputs.json') if shots_root else ''
        if path and os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                rec = json.load(f)
            if not isinstance(rec, dict) or not isinstance(rec.get('inputs'), dict):
                raise ValueError(f'shots/{r["id"]}/inputs.json: want {{"inputs": {{...}}}}')
            wf = str(rec.get('workflow') or 'inspect.yml')
            if wf not in RECREATE_WORKFLOWS:
                raise ValueError(f'shots/{r["id"]}/inputs.json: workflow must be one of {", ".join(RECREATE_WORKFLOWS)}')
            got = _inputs(rec['inputs'], f'shots/{r["id"]}/inputs.json', truncate=True)
            form = workflow_form(wf)[1]
            # known inputs only, in form order (all of them when the workflow file is not at hand)
            r['inputs'] = {k: got[k] for k in form if k in got} if form else got
            r['inputs_src'], r['workflow'] = 'run', wf
        elif r.get('recreate') is not None:
            r['inputs'], r['inputs_src'] = dict(r['recreate']), 'spec'


def changed_inputs(inputs: dict, wf: str = 'inspect.yml') -> dict:
    """The inputs that differ from that workflow form's defaults (what someone has to type)."""
    form = workflow_form(wf)[1]
    return {k: v for k, v in inputs.items() if v != form.get(k, '')}


def settings_text(r: dict) -> str:
    """Short settings of a run: source, app, extra, api_level, patches, cache."""
    i = r.get('inputs')
    if r.get('settings') or not i:  # the spec's own words win; derived text only when it gives none
        return r.get('settings') or 'not recorded'
    if i.get('apk_url'):
        src = 'apk_url'
    elif i.get('artifact_run'):
        src = f'artifact {i.get("artifact_name", "")} of run {i["artifact_run"]}'
    elif i.get('repo'):
        ref = i.get('ref') or 'HEAD'
        src = f'{i["repo"]}@{ref[:7] if HEX.fullmatch(ref) else ref}'
    else:
        src = 'this repo'
    parts = [src]
    if i.get('app'):
        parts.append(f'app {i["app"]}')
    if i.get('extra'):
        parts.append(f'extra {i["extra"]}')
    form = workflow_form(r.get('workflow') or 'inspect.yml')[1]
    if i.get('api_level') or form.get('api_level'):
        parts.append(f'api_level {i.get("api_level") or form["api_level"]}')
    if i.get('device') or form.get('device'):  # devicelab.yml: the lab phone model + its API level
        parts.append(f'device {i.get("device") or form["device"]} API {i.get("version") or form.get("version", "")}'.rstrip())
    if i.get('patches'):
        parts.append('patches ' + ', '.join(os.path.basename(p.strip()) for p in i['patches'].split(';') if p.strip()))
    if 'cache' in form or not form:  # only a workflow that has a cache input (devicelab.yml has none)
        parts.append(f'cache {i.get("cache") or "off"}')
    return short(' · '.join(parts), SETTINGS_MAX)


def too_long_note(r: dict) -> str:
    return f'<value too long: copy it from shots/{r["id"]}/inputs.json on branch shots>'


def recreate_json(r: dict) -> str:
    """The changed inputs as JSON for `gh workflow run --json`; a truncated value is replaced by a
    placeholder (a cut value must never be sent as if it were the real one)."""
    changed = changed_inputs(r['inputs'], r.get('workflow') or 'inspect.yml')
    changed = {k: (too_long_note(r) if v.endswith(TRUNC_MARK) else v) for k, v in changed.items()}
    return json.dumps(changed, indent=1, ensure_ascii=False)


def anchor(r: dict) -> str:
    return f'recreate-run-{r["id"]}'  # = GitHub's heading anchor of '### Recreate run <id>'


def recreate_view(r: dict, repo: str) -> dict:
    """One run's hand-held steps as plain data: {heading, lines, steps, pre} (escaped by each renderer)."""
    out = {'heading': f'Recreate run {r["id"]}', 'id': anchor(r), 'lines': [], 'steps': [], 'pre': ''}
    if not r.get('inputs'):
        out['lines'] = [f'Run {r["id"]} ({r["label"]}): settings not recorded.',
                        'It has no inputs.json and the report spec gives no recreate inputs for it.']
        return out
    src = ('These settings were recorded by the run itself (shots/<id>/inputs.json).' if r['inputs_src'] == 'run'
           else 'These settings come from the report spec, not from the run itself.')
    wf = r.get('workflow') or 'inspect.yml'
    again = ('A new run tests the same APK artifact again on a lab phone: it reproduces the inputs, not that exact run.'
             if wf == 'devicelab.yml' else 'A new run builds again: it reproduces the inputs, not the exact bytes of that run.')
    out['lines'] = [f'Run {r["id"]} ({r["label"]}).', src, again]
    wf_name = workflow_form(wf)[0] or wf
    out['workflow'], out['workflow_name'] = wf, wf_name
    changed = changed_inputs(r['inputs'], wf)
    # steps = [(text, value or None)]: a value is shown as code (copied exactly), the text is escaped
    out['steps'] = [(f'Open the Actions tab of {repo or "this repo"}, then pick "{wf_name}" ({wf}) in the workflow list on the left.', None),
                    ('Click "Run workflow" (top right of the run list); keep the branch "main".', None)]
    out['steps'] += [(f'Set the field "{k}" to its full value from shots/{r["id"]}/inputs.json on branch shots '
                      '(too long to show here; the gh command below has a placeholder for it).', None)
                     if v.endswith(TRUNC_MARK) else (f'Set the field "{k}" to:', v) if v else (f'Empty the field "{k}".', None)
                     for k, v in changed.items()]
    out['steps'] += [('Leave every other field at its default.' if changed else 'Leave every field at its default.', None),
                     ('Click the green "Run workflow" button.', None)]
    repo_arg = f' --repo {repo}' if repo else ''
    out['pre'] = f"gh workflow run {wf}{repo_arg} --ref main --json <<'JSON'\n{recreate_json(r)}\nJSON"
    return out


class Ctx:
    """URLs of one report: shots/<slug>/ on branch `shots` of repo OWNER/NAME."""

    def __init__(self, repo: str, slug: str):
        if not REPO.fullmatch(repo or ''):
            raise ValueError(f'bad repo: {repo!r}')
        if not SLUG.fullmatch(slug or ''):
            raise ValueError(f'bad slug: {slug!r}')
        owner, name = repo.split('/')
        self.repo, self.slug = repo, slug
        self.pages_host = f'{owner.lower()}.github.io'
        self.pages = f'https://{self.pages_host}/{name}/shots'
        self.raw = f'https://raw.githubusercontent.com/{repo}/shots/shots'
        self.page = f'{self.pages}/{slug}/'
        self.sheet = f'{self.pages}/{slug}/sheet.png'
        self.embed = f'{self.pages}/{slug}/embed.png'
        self.tests = f'https://github.com/{repo}/blob/shots/shots/{slug}/TESTS.md'
        self.actions = f'https://github.com/{repo}/actions/workflows/'  # + <workflow>.yml

    def run_url(self, rid):
        return f'https://github.com/{self.repo}/actions/runs/{rid}'

    def run_page(self, rid):
        return f'{self.pages}/{rid}/'

    def png(self, rid, name):
        return f'{self.raw}/{rid}/{name}'

    def pages_file(self, rid, name):
        return f'{self.pages}/{rid}/{name}'


def summary_view(card: dict, runs: list, ctx) -> dict | None:
    """spec `summary` -> {bug, fix, code, lang, proof, links: [(text, url or None)]}; a proof run links
    to its run page on GitHub (no --repo: its label only, no URL)."""
    sm = validate_summary(card, {r['id'] for r in runs})
    if not sm:
        return None
    by_id = {r['id']: r for r in runs}
    links = [(f'{by_id[rid]["label"]} (run {rid})', ctx.run_url(rid) if ctx else None) for rid in sm['proof_runs']]
    links += [(t, u) for t, u in sm['proof_links']]
    return dict(sm, links=links)


VERDICTS = {'CRASH': 'crash', 'FAIL': 'crash', 'FAILED': 'crash', 'CLEAN': 'clean', 'PASS': 'clean'}
VERDICT_EMOJI = {'crash': '🔴', 'clean': '🟢'}
VERDICT_LEAD = re.compile(r'\s*([A-Za-z]+)\s*[:,]\s*')  # the result's first word, directly followed by ':' or ','
PHONE_INTRO = "Firebase Test Lab runs on Google's lab phones. Every image and video here was looked at before publishing."


def verdict(result: str) -> tuple:
    """(WORD, kind) from a run's result: its first word when directly followed by ':' or ',' (any case), if it
    is a known verdict word (VERDICTS: CRASH / FAIL / FAILED -> 'crash', CLEAN / PASS -> 'clean'); else
    ('', 'neutral'). "Clean install crashed: x" and "Crash-free run: yes" are neutral."""
    m = VERDICT_LEAD.match(result or '')
    word = m[1].upper() if m else ''
    return (word, VERDICTS[word]) if word in VERDICTS else ('', 'neutral')


def result_shown(result: str) -> str:
    """The result as displayed next to its badge / emoji: a leading 'WORD:' / 'WORD,' that is the verdict is
    dropped (the badge already says it); any other result is shown whole."""
    m = VERDICT_LEAD.match(result or '')
    return result[m.end():] if m and m[1].upper() in VERDICTS and result[m.end():].strip() else (result or '')


def is_phone(r: dict) -> bool:
    return bool(r.get('phone')) or r.get('workflow') == 'devicelab.yml'


def where_ran(r: dict) -> str:
    """Where a run ran, derived from its workflow / devicelab.json / inputs; '' when unknown."""
    i = r.get('inputs') or {}
    if is_phone(r):
        form = workflow_form('devicelab.yml')[1] if i else {}  # an input left out = its form default (as in Settings)
        d, ver = i.get('device') or form.get('device'), i.get('version') or form.get('version') or ''
        dev = ((r.get('phone') or {}).get('facts') or {}).get('device') or (f'{d} API {ver}'.strip() if d else '')
        return ('Physical phone in Google Firebase Test Lab (devicelab.yml)' +
                (f': device {dev}' if dev else '') + ', not an emulator')
    if r.get('workflow', 'inspect.yml') == 'inspect.yml' and (i or r.get('picked')):
        if i.get('static_only') == 'true':
            return 'GitHub Actions runner (inspect.yml): static APK checks only, no emulator'
        form = workflow_form('inspect.yml')[1]
        prof = (f'; profile {i.get("profile") or form.get("profile") or "?"}, API {i.get("api_level") or form.get("api_level") or "?"}'
                if i else '')
        return f'GitHub Actions emulator (inspect.yml; x86_64, software-rendered{prof})'
    return ''


def run_view(r: dict, ctx) -> dict:
    """ONE block per run, as plain data (each renderer escapes it): {id, label, word, kind, rows:
    [(name, text)] in order (empty rows skipped; Result first), links: [(text, url)], recreate (anchor),
    video, strip, images, sheet (URLs; ctx only), shot_names}."""
    word, kind = verdict(r['result'])
    tags = ' · '.join(t.upper() if t in CACHES else t for t in (r['cache'], r['status']) if t)
    ph = r.get('phone') or {}
    facts = phone_line(r).split(': ', 1)[-1] if phone_line(r) else ''
    rows = [('Result', result_shown(r['result']) if word else r['result']),('What we learned', r.get('learned') or ''), ('Question', r['question']),
            ('Where it ran', where_ran(r)), ('Settings', settings_text(r)), ('Test Lab', facts), ('Evidence', tags)]
    rows += [('Note', n) for n in ph.get('notes') or []]
    v = {'id': r['id'], 'label': r['label'], 'word': word, 'kind': kind, 'rows': [x for x in rows if x[1]],
         'links': [], 'recreate': anchor(r), 'video': '', 'strip': '', 'images': [], 'sheet': '', 'shot_names': []}
    if ctx:
        v['links'] = [('Actions run', ctx.run_url(r['id']))] + ([('run card', ctx.run_page(r['id']))] if r.get('has_page') else [])
        shown = ph['images'] if ph else (r.get('picked') or [])  # a phone run: ALL its published screenshots
        v['images'] = [ctx.png(r['id'], i) for i in shown]
        v['shot_names'] = shown
        if ph.get('strip'):
            v['strip'] = ctx.png(r['id'], ph['strip'])
        if ph.get('video'):
            v['video'] = ctx.pages_file(r['id'], ph['video'])
        if ph.get('sheet'):
            v['sheet'] = ctx.png(r['id'], ph['sheet'])
    return v


def embed_items(card: dict, runs: list, shots_root: str) -> list:
    """[{label, images: [path]}] for contact_sheet.py --groups: one tile per `embed` item."""
    by_id = {r['id']: r for r in runs}
    out = []
    for e in card.get('embed') or []:
        rid = str(e['run'])
        path = os.path.join(shots_root, 'shots', rid, e['image'])
        if not os.path.isfile(path):
            raise ValueError(f'embed: not in shots/{rid}/: {e["image"]}')
        out.append({'label': e.get('caption') or by_id[rid]['label'], 'images': [path]})
    return out


def expand(card: dict, runs: list, ctx, embed=False) -> dict:
    """The HTML view's card: key points, the spec's sections, one section per run (a view of
    `runs`), then "How to recreate" (one section per run, anchored)."""
    card = dict(card)
    if ctx:
        card['url'] = ctx.page
        if any(r.get('picked') for r in runs):
            card['image'] = ctx.sheet
        if embed:
            card['sheet_image'] = card.get('image')
            card['image'] = ctx.embed
    card['summary_view'] = summary_view(card, runs, ctx)
    sections = list(card.get('sections') or [])
    if runs:  # ONE block per run (run_view): verdict, a table of everything about it, then its media
        sections.append({'heading': 'Runs', 'id': 'runs',
                         'lines': [PHONE_INTRO] if ctx and any(r.get('phone') for r in runs) else []})
        sections += [{'id': f'run-{r["id"]}', 'run': run_view(r, ctx)} for r in runs]
    if runs:
        sections.append({'heading': 'How to recreate', 'id': 'how-to-recreate',
                         'lines': ['Each run below: its settings, step by step in the Actions tab, and the same as one gh command.']})
        sections += [recreate_view(r, ctx.repo if ctx else '') for r in runs]
    card['sections'] = sections
    return card


ANCHOR = re.compile(r'[a-z0-9-]{1,80}')


def render(card: dict, hosts=ALLOWED_HOSTS, extra_links=()) -> str:
    """card -> HTML string. card keys: title, description, url, image (optional if a section
    has one), key_points, sheet_image, summary_view (above the title), sections: [{heading, text,
    diagram, lines, image, images, strip, video, links, anchor_links, steps, pre, page, id}] (all optional).
    A CSP meta allows no script at all, or (a page with a diagram) only the pinned Mermaid file + its init."""
    hosts = tuple(h.lower() for h in hosts)
    e = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    u = lambda s: e(check_url(s, hosts))  # noqa: E731

    def a(s):  # an in-page anchor
        if not ANCHOR.fullmatch(s):
            raise ValueError(f'bad anchor: {s!r}')
        return s
    sections = card.get('sections') or []
    image = card.get('image') or next((s['image'] for s in sections if s.get('image')), None)
    if not image:
        raise ValueError('card needs an image (card.image, a section image, or runs with screenshots)')
    title = short(card['title'], 256)
    desc = short(card.get('description', ''))
    meta = [
        ('property', 'og:type', 'website'),
        ('property', 'og:title', e(title)),
        ('property', 'og:description', e(desc)),
        ('property', 'og:image', u(image)),
        ('property', 'og:url', u(card['url'])),
        ('name', 'twitter:card', 'summary_large_image'),
        ('name', 'twitter:title', e(title)),
        ('name', 'twitter:description', e(desc)),
        ('name', 'twitter:image', u(image)),
        ('name', 'theme-color', THEME),
        ('name', 'description', e(desc)),
    ]
    diagrams = [validate_diagram(s['diagram'], 'diagram') for s in sections if s.get('diagram') is not None]
    out = ['<!doctype html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
           f'<meta http-equiv="Content-Security-Policy" content="{e(csp(bool(diagrams), hosts))}">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f'<title>{e(title)}</title>']
    out += [f'<meta {k}="{n}" content="{v}">' for k, n, v in meta]
    out += ['<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:0 auto;'
            'padding:16px;background:#111;color:#eee}a{color:#8cf}img{max-width:100%;height:auto;'
            'display:block;margin:8px 0}section{border-top:1px solid #444;margin-top:24px}'
            'p{margin:4px 0}pre{background:#222;padding:8px;overflow-x:auto;white-space:pre-wrap}'
            '.shots{display:flex;flex-wrap:wrap;gap:8px}.shots img{max-width:240px}'
            'video{max-width:100%;width:360px;display:block;margin:8px 0}'
            '.summary{background:#1b2533;border:1px solid #2b6cb0;padding:8px 8px 8px 32px}'
            '.summary pre{background:#0b0f14}' + (RUN_CSS if any(s.get('run') for s in sections) else '') + '</style>',
            '</head>', '<body>']
    sv = card.get('summary_view')
    if sv:  # the author's three top bullets, ABOVE the title: bug, fix (+ code), proof links
        proof = ' · '.join(f'<a href="{u(href)}">{e(text)}</a>' if href else e(text) for text, href in sv['links'])
        code = f'<pre><code>{e(sv["code"])}</code></pre>' if sv['code'] else ''
        out.append('<ol class="summary">'
                   f'<li><strong>Bug:</strong> {e(sv["bug"])}</li>'
                   f'<li><strong>Fix:</strong> {e(sv["fix"])}{code}</li>'
                   f'<li><strong>Proof:</strong> {e(sv["proof"]) + " " if sv["proof"] else ""}{proof}</li></ol>')
    out.append(f'<h1>{e(title)}</h1>')
    if card.get('key_points'):
        out.append('<ul class="key">' + ''.join(f'<li>{e(k)}</li>' for k in card['key_points']) + '</ul>')
    if card.get('description'):
        out += html_blocks(card['description'], e)
    if extra_links:
        out.append('<p>' + ' · '.join(f'<a href="{u(href)}">{e(text)}</a>' for text, href in extra_links) + '</p>')
    if card.get('image'):
        out.append(f'<img src="{u(card["image"])}" alt="{e(title)}">')
    if card.get('sheet_image'):
        out += ['<p>All screenshots (contact sheet):</p>',
                f'<a href="{u(card["sheet_image"])}"><img src="{u(card["sheet_image"])}" alt="contact sheet"></a>']
    for s in sections:
        out.append(f'<section id="{a(s["id"])}">' if s.get('id') else '<section>')
        if s.get('run'):
            out += run_html(s['run'], e, u, a)
            out.append('</section>')
            continue
        if s.get('heading'):
            h = e(s['heading'])
            out.append(f'<h2><a href="{u(s["page"])}">{h}</a></h2>' if s.get('page') else f'<h2>{h}</h2>')
        if s.get('text'):
            out += html_blocks(s['text'], e)
        if s.get('diagram') is not None:  # mermaid reads the element's text: escaped here, inert as HTML
            out.append(f'<pre class="mermaid">{e(validate_diagram(s["diagram"], "diagram"))}</pre>')
        out += [f'<p>{e(line)}</p>' for line in s.get('lines') or []]
        if s.get('anchor_links'):
            out.append('<p>' + ' · '.join(f'<a href="#{a(t)}">{e(x)}</a>' for x, t in s['anchor_links']) + '</p>')
        if s.get('steps'):
            out.append('<ol>' + ''.join(f'<li>{e(x)}' + (f' <code>{e(v)}</code>' if v else '') + '</li>'
                                        for x, v in s['steps']) + '</ol>')
        if s.get('pre'):
            out.append(f'<pre>{e(s["pre"])}</pre>')
        if s.get('image') and s['image'] != card.get('image'):
            out.append(f'<a href="{u(s["image"])}"><img src="{u(s["image"])}" alt="contact sheet"></a>')
        if s.get('strip'):
            out += ['<p>Frames sampled from the video:</p>',
                    f'<a href="{u(s["strip"])}"><img src="{u(s["strip"])}" alt="video frames" loading="lazy"></a>']
        if s.get('video'):
            out.append(f'<video controls preload="metadata" playsinline src="{u(s["video"])}"></video>')
        if s.get('images'):
            out.append('<div class="shots">')
            out += [f'<a href="{u(i)}"><img src="{u(i)}" alt="{e(i.rsplit("/", 1)[-1])}" loading="lazy"></a>'
                    for i in s['images']]
            out.append('</div>')
        if s.get('links'):
            out.append('<ul>')
            out += [f'<li><a href="{u(href)}">{e(text)}</a></li>' for text, href in s['links']]
            out.append('</ul>')
        out.append('</section>')
    if diagrams:
        out += [f'<script src="{e(MERMAID_URL)}" integrity="{e(MERMAID_SRI)}" crossorigin="anonymous"></script>',
                f'<script>{MERMAID_INIT}</script>']
    out += ['</body>', '</html>', '']
    return '\n'.join(out)


RUN_CSS = ('table.run{border-collapse:collapse;margin:8px 0;max-width:100%}'
           'table.run th,table.run td{border:1px solid #444;padding:4px 8px;text-align:left;vertical-align:top}'
           'table.run th{white-space:nowrap;color:#bbb;font-weight:600}'
           '.badge{display:inline-block;border-radius:4px;padding:0 8px;font-size:.75em;vertical-align:middle;color:#fff}'
           '.badge.crash{background:#c53030}.badge.clean{background:#2f855a}'
           'tr.crash th,tr.crash td{background:#3d1a1a}tr.clean th,tr.clean td{background:#173b26}')


def run_html(v: dict, e, u, a) -> list:
    """One run block (run_view) -> HTML lines: <h3> label + verdict badge, the rows table (Result row
    tinted by verdict), then video, frame strip and screenshots. Text through e(), URLs through u()."""
    badge = f' <span class="badge {v["kind"]}">{e(v["word"])}</span>' if v['word'] else ''
    out = [f'<h3>{e(v["label"])}{badge}</h3>', '<table class="run">']
    for name, text in v['rows']:
        tint = f' class="{v["kind"]}"' if name == 'Result' and v['word'] else ''
        out.append(f'<tr{tint}><th scope="row">{e(name)}</th><td>{e(text)}</td></tr>')
    links = [f'<a href="{u(href)}">{e(text)}</a>' for text, href in v['links']]
    if v['video']:
        links.append(f'<a href="{u(v["video"])}">video (mp4)</a>')
    links.append(f'<a href="#{a(v["recreate"])}">how to recreate</a>')
    out += [f'<tr><th scope="row">Links</th><td>{" · ".join(links)}</td></tr>', '</table>']
    if v['video']:
        out.append(f'<video controls preload="metadata" playsinline src="{u(v["video"])}"></video>')
    if v['strip']:
        out += ['<p>Frames sampled from the video:</p>',
                f'<a href="{u(v["strip"])}"><img src="{u(v["strip"])}" alt="video frames" loading="lazy"></a>']
    if v['images']:
        out.append('<div class="shots">')
        out += [f'<a href="{u(i)}"><img src="{u(i)}" alt="{e(i.rsplit("/", 1)[-1])}" loading="lazy"></a>' for i in v['images']]
        out.append('</div>')
    return out


def csp(scripts: bool, hosts=ALLOWED_HOSTS) -> str:
    """Content-Security-Policy of a card page: images / video only from the allowlisted hosts that serve
    files (raw.githubusercontent.com, the Pages host, any --allow-host; not github.com, whose image
    links redirect elsewhere), our inline style; scripts = the pinned Mermaid file (SRI-checked too) +
    the inline init, allowed by its sha256."""
    init = base64.b64encode(hashlib.sha256(MERMAID_INIT.encode()).digest()).decode()
    script = f"{MERMAID_URL} 'sha256-{init}'" if scripts else "'none'"
    src = ' '.join(f'https://{h}' for h in dict.fromkeys(hosts) if h != 'github.com') or "'none'"
    return (f"default-src 'none'; img-src {src}; media-src {src}; style-src 'unsafe-inline'; "
            f"script-src {script}; base-uri 'none'; form-action 'none'")


def fence(text: str) -> str:
    """A code fence longer than any backtick run in text."""
    runs = [len(m) for m in re.findall(r'`+', text)]
    return '`' * max(3, max(runs, default=0) + 1)


def code(value: str) -> str:
    """value -> an inline code span (shown and copied exactly; markdown / HTML inert inside)."""
    value = ' '.join(str(value).split())
    ticks = '`' * (max([len(m) for m in re.findall(r'`+', value)], default=0) + 1)
    pad = ' ' if value.startswith('`') or value.endswith('`') else ''
    return f'{ticks}{pad}{value}{pad}{ticks}'


def run_md(v: dict, link, dest) -> list:
    """One run block (run_view) -> TESTS.md lines: an anchor (#run-<id>), '### label · emoji VERDICT', a
    2-column table (bold row names; Result led by emoji + **VERDICT**), then video link, frame strip,
    screenshot sheet and screenshot links. Text through md(); links through link() / our own anchors."""
    emoji = VERDICT_EMOJI.get(v['kind'])
    out = [f'<a id="run-{v["id"]}"></a>', '',
           f'### {md(v["label"])}' + (f' · {emoji} {v["word"]}' if emoji else ''), '',
           '| Field | Value |', '|---|---|']
    for name, text in v['rows']:
        lead = f'{emoji} **{v["word"]}** ' if name == 'Result' and emoji else ''
        out.append(f'| **{md(name)}** | {lead}{md(text)} |')
    links = [link(t, h) for t, h in v['links']] + [f'[how to recreate](#{v["recreate"]})']
    out += [f'| **Links** | {" · ".join(links)} |', '']
    if v['video']:
        out += [f'Video: {link("video.mp4", v["video"])}', '']
    if v['strip']:
        out += ['Frames sampled from the video:', '', f'![video frames]({dest(v["strip"])})', '']
    if v['sheet']:
        out += ['All published screenshots:', '', f'![screenshots]({dest(v["sheet"])})', '']
    if v['images']:
        out += [' '.join(link(os.path.splitext(n)[0], i) for n, i in zip(v['shot_names'], v['images'])), '']
    return out


def render_md(card: dict, runs: list, ctx, hosts=ALLOWED_HOSTS) -> str:
    """The TESTS.md view (GitHub-rendered) of the same spec: title, key points, description, a table
    of every run (leftmost column = settings + a link to its recreate steps), sections, then
    "How to recreate". Links only through link() (allowlisted https) or to our own anchors; all
    text through md(); the gh command sits in a code block (not rendered)."""
    hosts = tuple(h.lower() for h in hosts)

    def dest(href):  # allowlisted, and nothing that could end the link / table cell early
        if not MD_URL.fullmatch(check_url(href, hosts)):
            raise ValueError(f'URL has characters markdown would misread: {href!r}')
        return href
    link = lambda text, href: f'[{md(text)}]({dest(href)})'  # noqa: E731
    out = []
    sv = summary_view(card, runs, ctx)
    if sv:  # the author's three top bullets, ABOVE the title; the code sits in a fence (shown, never rendered)
        proof = ' · '.join(link(t, h) if h else md(t) for t, h in sv['links'])
        out += [f'1. **Bug:** {md(sv["bug"])}', f'2. **Fix:** {md(sv["fix"])}', '']
        if sv['code']:
            f = fence(sv['code'])
            out += [f'   {f}{sv["lang"]}'] + [f'   {x}' if x else '' for x in sv['code'].split('\n')] + [f'   {f}', '']
        out += [f'3. **Proof:** {md(sv["proof"]) + " " if sv["proof"] else ""}{proof}', '']
    out += [f'# {md(card["title"], 256)}', '']
    if card.get('key_points'):
        out += [f'- {md(k)}' for k in card['key_points']] + ['']
    if card.get('description'):
        out += md_blocks(card['description'])
    if ctx:
        top = [link('card page', ctx.page)]
        if any(r.get('picked') for r in runs):
            top.append(link('contact sheet', ctx.sheet))
        out += [' · '.join(top), '']
        if any(r.get('picked') for r in runs):
            out += [f'![contact sheet]({dest(ctx.sheet)})', '']
    if runs:
        out += ['| Settings / recreate | # | run | question | result | cache | status | screenshots |',
                '|---|---|---|---|---|---|---|---|']
        for k, r in enumerate(runs, 1):
            if ctx:
                cell = link(r['label'], ctx.run_url(r['id']))
                if r.get('has_page'):  # only an existing run card page is linked
                    cell += f' ({link("card", ctx.run_page(r["id"]))})'
                pngs = ' '.join(link(os.path.splitext(i)[0], ctx.png(r['id'], i)) for i in r.get('picked') or [])
                if r.get('phone'):
                    pngs = (pngs + ' · ' if pngs else '') + f'[phone media](#run-{r["id"]})'

            else:
                cell, pngs = f'{md(r["label"])} (run {r["id"]})', ''
            settings = f'{md(settings_text(r))} · [how to recreate](#{anchor(r)})'
            word, kind = verdict(r['result'])
            emoji = VERDICT_EMOJI.get(kind)
            result = f'{emoji} **{word}** {md(result_shown(r["result"]))}' if emoji else (md(r['result']) or ' ')
            out.append(f'| {settings} | {k} | {cell} | {md(r["question"]) or " "} | {result} | '
                       f'{r["cache"] or " "} | {r["status"] or " "} | {pngs or "none"} |')
        out.append('')
        out += ['## Runs', '']
        if ctx and any(r.get('phone') for r in runs):
            out += [md(PHONE_INTRO), '']
        for r in runs:  # ONE block per run (run_view); its recreate steps stay in "How to recreate" (linked)
            out += run_md(run_view(r, ctx), link, dest)
    for s in card.get('sections') or []:
        if s.get('heading'):
            out += [f'## {link(s["heading"], s["page"]) if s.get("page") else md(s["heading"])}', '']
        if s.get('text'):
            out += md_blocks(s['text'])
        if s.get('diagram') is not None:  # GitHub renders the fence (its own sandbox); validated anyway
            d = validate_diagram(s['diagram'], 'diagram')
            out += [f'{fence(d)}mermaid', d, fence(d), '']
        items = ([link('contact sheet', s['image'])] if s.get('image') else []) + \
            [link(i.rsplit('/', 1)[-1], i) for i in s.get('images') or []] + \
            [link(text, href) for text, href in s.get('links') or []]
        out += [f'- {i}' for i in items] + ([''] if items else [])
    if runs:
        out += ['## How to recreate', '',
                'Each run below: its settings, step by step in the Actions tab, and the same as one gh command.', '']
        for r in runs:
            v = recreate_view(r, ctx.repo if ctx else '')
            out += [f'### {v["heading"]}', '']
            for line in v['lines']:  # one idea per line: each its own paragraph
                out += [md(line), '']
            if v['steps']:
                items = [md(x) + (f' {code(val)}' if val else '') for x, val in v['steps']]
                if ctx:  # the first step as a link to the inspect workflow page
                    items[0] = f'Open the {md(v["workflow_name"])} workflow in the Actions tab: {link(v["workflow"], ctx.actions + v["workflow"])}.'
                out += [f'{n}. {x}' for n, x in enumerate(items, 1)] + ['']
            if v['pre']:
                f = fence(v['pre'])
                out += ['Or with the GitHub CLI (`gh`):', '', f'{f}sh', v['pre'], f, '']
    return '\n'.join(out)


def write(path: str, card: dict, hosts=ALLOWED_HOSTS, extra_links=()) -> None:
    page = render(card, hosts, extra_links)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(page)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('out', nargs='?')
    ap.add_argument('--spec', help='JSON card spec (any mode, incl. a multi-run report)')
    ap.add_argument('--title')
    ap.add_argument('--description', default='')
    ap.add_argument('--image', help='og:image: absolute https URL (the contact sheet)')
    ap.add_argument('--url', help='og:url: the page\'s own URL')
    ap.add_argument('--img', action='append', default=[], help='a per-PNG image URL (repeat)')
    ap.add_argument('--link', action='append', default=[], help="'text=URL' (repeat)")
    ap.add_argument('--allow-host', action='append', default=[], help='extra allowed host (e.g. a fork\'s Pages host)')
    ap.add_argument('--repo', help='OWNER/NAME: build the report URLs (needs --slug)')
    ap.add_argument('--slug', help='the report folder shots/<slug>/')
    ap.add_argument('--shots-root', help='a checkout of branch shots: pick each run\'s PNGs (+ inputs.json) from it')
    ap.add_argument('--md', help='also write the TESTS.md view here')
    ap.add_argument('--sheet-manifest', help='also write the contact_sheet.py --groups manifest here')
    ap.add_argument('--embed-manifest', help='also write the highlights (embed.png) manifest here; og:image = embed.png')
    ap.add_argument('--run-ids', action='store_true', help='validate the spec, print run ids, write nothing')
    ap.add_argument('--media-plan', help='with --run-ids: also write the cleared phone media plan (JSON list) here; '
                    'with --shots-root, runs already published there (no "replace": true) are left out')
    a = ap.parse_args()
    hosts = ALLOWED_HOSTS + tuple(a.allow_host)
    if a.spec:
        try:
            with open(a.spec, encoding='utf-8') as f:
                card = json.load(f)
        except (OSError, ValueError) as exc:
            print(f'card_page: cannot read spec {a.spec!r}: {exc}', file=sys.stderr)
            return 2
        if not isinstance(card, dict):
            print('card_page: spec must be a JSON object', file=sys.stderr)
            return 2
    else:
        if a.run_ids or a.md or a.repo:
            ap.error('--run-ids, --md and --repo need --spec')
        if not (a.title and a.image and a.url):
            ap.error('--title, --image and --url are required without --spec')
        links = []
        for item in a.link:
            i = item.find('=https://')
            if i < 1:
                ap.error(f'--link needs text=https://...: {item!r}')
            links.append((item[:i], item[i + 1:]))
        card = {'title': a.title, 'description': a.description, 'image': a.image, 'url': a.url,
                'sections': [{'images': a.img, 'links': links}]}
    if not a.run_ids and not a.out:
        ap.error('OUT.html is required')
    try:
        runs = validate(card) if a.spec else []
        if a.run_ids:
            if a.media_plan:
                plan, kept = media_plan(runs, a.shots_root)
                with open(a.media_plan, 'w', encoding='utf-8', newline='\n') as f:
                    json.dump(plan, f, indent=1)
                for rid in kept:
                    print(f'notice: run {rid}: media already published in shots/{rid}/: kept as it is '
                          '(set "replace": true to replace it)', file=sys.stderr)
            print('\n'.join(r['id'] for r in runs))
            return 0
        ctx = Ctx(a.repo, a.slug) if (a.repo or a.slug) else None
        if ctx:
            hosts += (ctx.pages_host,) if ctx.pages_host not in hosts else ()
            if a.shots_root:
                pick_images(runs, a.shots_root)
                load_folders(runs, a.shots_root)
        elif a.shots_root or a.md or a.sheet_manifest or a.embed_manifest:
            raise ValueError('--shots-root, --md, --sheet-manifest and --embed-manifest need --repo and --slug')
        load_inputs(runs, a.shots_root)
        embed = []
        if a.embed_manifest and card.get('embed'):
            if not a.shots_root:
                raise ValueError('embed needs --shots-root (the runs\' PNGs)')
            embed = embed_items(card, runs, a.shots_root)
        view = expand(card, runs, ctx, embed=bool(embed))
        extra = [('TESTS.md (every run in a table)', ctx.tests)] if (ctx and a.md) else []
        page = render(view, hosts, extra)
        tests = render_md(card, runs, ctx, hosts) if a.md else None
        manifest = [{'label': r['label'], 'images': [os.path.join(a.shots_root, 'shots', r['id'], i)
                                                      for i in r['picked']]}
                    for r in runs if r.get('picked')] if a.shots_root else []
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        # bad values or a malformed spec (wrong types / shapes): one clean line, exit 2
        print(f'card_page: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(page)
    print(f'{a.out}: card page written')
    desc_len = len(' '.join(str(card.get('description', '')).split()))
    if desc_len > DESC_WARN:
        print(f'warning: og:description is {desc_len} chars (over {DESC_WARN}: Discord cuts it; '
              f'the page keeps the first {DESC_MAX})')
    if tests is not None:
        with open(a.md, 'w', encoding='utf-8', newline='\n') as f:
            f.write(tests)
        print(f'{a.md}: TESTS.md written ({len(runs)} runs)')
    if a.sheet_manifest:
        with open(a.sheet_manifest, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(manifest, f, indent=1)
        print(f'{a.sheet_manifest}: {sum(len(g["images"]) for g in manifest)} images in {len(manifest)} runs')
    if a.embed_manifest:
        with open(a.embed_manifest, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(embed, f, indent=1)
        print(f'{a.embed_manifest}: {len(embed)} highlight image(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
