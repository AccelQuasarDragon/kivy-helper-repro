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
The og:description is cut to 200 chars (Discord truncates longer ones anyway); over 180 chars
prints a `warning:` line (report.yml copies it to its summary).

CLI (run card):
  card_page.py OUT.html --title T --description D --image SHEET_URL --url PAGE_URL \
      [--img PNG_URL ...] [--link 'text=URL' ...] [--allow-host HOST ...]
CLI (any card, incl. a report) from a JSON spec:
  card_page.py OUT.html --spec card.json [--allow-host HOST ...]
      [--repo OWNER/NAME --slug SLUG [--shots-root DIR] [--md TESTS.md] [--sheet-manifest M.json]
       [--embed-manifest E.json]]
  card_page.py --spec card.json --run-ids      (validate only; print the runs' ids, one per line)
  spec = {"title", "description", "image", "url",
          "key_points": ["most important fact", ...],
          "sections": [{"heading", "text", "image", "images": [...], "links": [[text, url], ...],
                        "page": url}],
          "runs": [{"id": 123, "label", "question", "result", "cache": "cold|warm|apk",
                    "status": "proven|inferred", "images": ["launch.png", ...],
                    "settings": "short text", "recreate": {"input": "value", ...},
                    "workflow": "inspect.yml|build.yml (the form `recreate` fills; default inspect.yml)"}],
          "embed": [{"run": 123, "image": "00_launch.png", "caption": "..."}]}
  With --repo/--slug, "url" = the Pages page of shots/<slug>/ and run URLs are built from the ids.
  --shots-root = a checkout of branch `shots`: each run's PNGs are picked from DIR/shots/<id>/
  (its `images`, else the first PER_RUN_DEFAULT; at most SHEET_MAX tiles in all); when any PNG is
  picked, og:image = shots/<slug>/sheet.png (render it from --sheet-manifest). Each run's
  DIR/shots/<id>/inputs.json (written by inspect.yml's shots job) gives its settings + recreate steps.
  With `embed` and --embed-manifest: og:image = shots/<slug>/embed.png instead (a highlights sheet,
  contact_sheet.py --groups E.json --height 900 --font-size 36); the full sheet stays on the page.
Locally: uv run --no-project tools/card_page.py ...
Exit codes: 0 written, 2 bad input (bad URL, malformed spec, missing key); argparse errors are 2 too.
Pass free text in the `=` form (--title="$LABEL") so a value like `--help` is not read as an option.
"""
import argparse
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
RECREATE_WORKFLOWS = ('inspect.yml', 'build.yml')  # workflows whose form a recreate section can fill
_FORMS = {}


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
    return out


def pick_images(runs: list, shots_root: str) -> None:
    """Set run['picked'] = the PNG names of shots_root/shots/<id>/ that go on the sheet and pages:
    a run's listed `images` (each must exist), else up to PER_RUN_DEFAULT of its sorted PNGs
    (sheet.png excluded), handed out round-robin so every run gets one before any gets more;
    at most SHEET_MAX in all."""
    avail = {}
    for r in runs:
        d = os.path.join(shots_root, 'shots', r['id'])
        names = sorted(f for f in os.listdir(d) if PNG.fullmatch(f) and f != 'sheet.png') \
            if os.path.isdir(d) else []
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
    if not i:
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
    if i.get('patches'):
        parts.append('patches ' + ', '.join(os.path.basename(p.strip()) for p in i['patches'].split(';') if p.strip()))
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
                        'It has no inputs.json (runs before 2026-11-16 did not write one).',
                        'The report spec gives no recreate inputs for it either.']
        return out
    src = ('These settings were recorded by the run itself (shots/<id>/inputs.json).' if r['inputs_src'] == 'run'
           else 'These settings come from the report spec, not from the run itself.')
    out['lines'] = [f'Run {r["id"]} ({r["label"]}).', src,
                    'A new run builds again: it reproduces the inputs, not the exact bytes of that run.']
    wf = r.get('workflow') or 'inspect.yml'
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


def run_lines(r: dict) -> list:
    """Plain-text lines for a run, one idea per line (escaped by each renderer)."""
    tags = ' · '.join(t.upper() if t in CACHES else t for t in (r['cache'], r['status']) if t)
    lines = [f'Question: {r["question"]}' if r['question'] else '', f'Result: {r["result"]}' if r['result'] else '',
             f'Evidence: {tags}' if tags else '', f'Settings: {settings_text(r)}']
    return [x for x in lines if x]


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
    sections = list(card.get('sections') or [])
    for r in runs:
        s = {'heading': r['label'], 'lines': run_lines(r), 'anchor_links': [('how to recreate', anchor(r))]}
        if ctx:
            s['page'] = ctx.run_page(r['id'])
            s['images'] = [ctx.png(r['id'], i) for i in r.get('picked') or []]
            s['links'] = [['run', ctx.run_url(r['id'])], ['run card', ctx.run_page(r['id'])]]
        sections.append(s)
    if runs:
        sections.append({'heading': 'How to recreate', 'id': 'how-to-recreate',
                         'lines': ['Each run below: its settings, step by step in the Actions tab, and the same as one gh command.']})
        sections += [recreate_view(r, ctx.repo if ctx else '') for r in runs]
    card['sections'] = sections
    return card


ANCHOR = re.compile(r'[a-z0-9-]{1,80}')


def render(card: dict, hosts=ALLOWED_HOSTS, extra_links=()) -> str:
    """card -> HTML string. card keys: title, description, url, image (optional if a section
    has one), key_points, sheet_image, sections: [{heading, text, lines, image, images, links,
    anchor_links, steps, pre, page, id}] (all optional)."""
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
    out = ['<!doctype html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f'<title>{e(title)}</title>']
    out += [f'<meta {k}="{n}" content="{v}">' for k, n, v in meta]
    out += ['<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:0 auto;'
            'padding:16px;background:#111;color:#eee}a{color:#8cf}img{max-width:100%;height:auto;'
            'display:block;margin:8px 0}section{border-top:1px solid #444;margin-top:24px}'
            'p{margin:4px 0}pre{background:#222;padding:8px;overflow-x:auto;white-space:pre-wrap}'
            '.shots{display:flex;flex-wrap:wrap;gap:8px}.shots img{max-width:240px}</style>',
            '</head>', '<body>', f'<h1>{e(title)}</h1>']
    if card.get('key_points'):
        out.append('<ul class="key">' + ''.join(f'<li>{e(k)}</li>' for k in card['key_points']) + '</ul>')
    if card.get('description'):
        out.append(f'<p>{e(card["description"])}</p>')
    if extra_links:
        out.append('<p>' + ' · '.join(f'<a href="{u(href)}">{e(text)}</a>' for text, href in extra_links) + '</p>')
    if card.get('image'):
        out.append(f'<img src="{u(card["image"])}" alt="{e(title)}">')
    if card.get('sheet_image'):
        out += ['<p>All screenshots (contact sheet):</p>',
                f'<a href="{u(card["sheet_image"])}"><img src="{u(card["sheet_image"])}" alt="contact sheet"></a>']
    for s in sections:
        out.append(f'<section id="{a(s["id"])}">' if s.get('id') else '<section>')
        if s.get('heading'):
            h = e(s['heading'])
            out.append(f'<h2><a href="{u(s["page"])}">{h}</a></h2>' if s.get('page') else f'<h2>{h}</h2>')
        if s.get('text'):
            out.append(f'<p>{e(s["text"])}</p>')
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
    out += ['</body>', '</html>', '']
    return '\n'.join(out)


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
    out = [f'# {md(card["title"], 256)}', '']
    if card.get('key_points'):
        out += [f'- {md(k)}' for k in card['key_points']] + ['']
    if card.get('description'):
        out += [md(card['description']), '']
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
                cell = f'{link(r["label"], ctx.run_url(r["id"]))} ({link("card", ctx.run_page(r["id"]))})'
                pngs = ' '.join(link(os.path.splitext(i)[0], ctx.png(r['id'], i)) for i in r.get('picked') or [])
            else:
                cell, pngs = f'{md(r["label"])} (run {r["id"]})', ''
            settings = f'{md(settings_text(r))} · [how to recreate](#{anchor(r)})'
            out.append(f'| {settings} | {k} | {cell} | {md(r["question"]) or " "} | {md(r["result"]) or " "} | '
                       f'{r["cache"] or " "} | {r["status"] or " "} | {pngs or "none"} |')
        out.append('')
    for s in card.get('sections') or []:
        if s.get('heading'):
            out += [f'## {link(s["heading"], s["page"]) if s.get("page") else md(s["heading"])}', '']
        if s.get('text'):
            out += [md(s['text']), '']
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
            print('\n'.join(r['id'] for r in runs))
            return 0
        ctx = Ctx(a.repo, a.slug) if (a.repo or a.slug) else None
        if ctx:
            hosts += (ctx.pages_host,) if ctx.pages_host not in hosts else ()
            if a.shots_root:
                pick_images(runs, a.shots_root)
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
