"""Generate a static HTML card page (Open Graph + Twitter tags) so a link pasted in Discord
unfurls as a rich embed: title + description + one big image. Stdlib only.

One spec, several views (docs/cards.md):
- run card: one section (a run's title, one-line result, contact sheet, per-PNG images, links)
- report card: several sections and/or a `runs` list; `runs` (the base data) generate the run
  sections of index.html, the table of TESTS.md (--md) and the contact-sheet manifest
  (--sheet-manifest, for contact_sheet.py --groups)

Every HTML text value is html.escape'd (quote=True); every markdown text value goes through md()
(markdown + HTML escaped, autolinks defused); every URL must be https on an allowed host.
The og:description is cut to 200 chars (Discord truncates longer ones anyway).

CLI (run card):
  card_page.py OUT.html --title T --description D --image SHEET_URL --url PAGE_URL \
      [--img PNG_URL ...] [--link 'text=URL' ...] [--allow-host HOST ...]
CLI (any card, incl. a report) from a JSON spec:
  card_page.py OUT.html --spec card.json [--allow-host HOST ...]
      [--repo OWNER/NAME --slug SLUG [--shots-root DIR] [--md TESTS.md] [--sheet-manifest M.json]]
  card_page.py --spec card.json --run-ids      (validate only; print the runs' ids, one per line)
  spec = {"title", "description", "image", "url",
          "sections": [{"heading", "text", "image", "images": [...], "links": [[text, url], ...],
                        "page": url}],
          "runs": [{"id": 123, "label", "question", "result", "cache": "cold|warm|apk",
                    "status": "proven|inferred", "images": ["launch.png", ...]}]}
  With --repo/--slug, "url" = the Pages page of shots/<slug>/ and run URLs are built from the ids.
  --shots-root = a checkout of branch `shots`: each run's PNGs are picked from DIR/shots/<id>/
  (its `images`, else the first PER_RUN_DEFAULT; at most SHEET_MAX tiles in all); when any PNG is
  picked, og:image = shots/<slug>/sheet.png (render it from --sheet-manifest).
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
DESC_MAX = 200
THEME = '#2b6cb0'
# spec shape limits (the workflow also caps the spec at 20000 chars)
RUNS_MAX, SECTIONS_MAX, LABEL_MAX, TEXT_MAX, IMAGES_MAX = 20, 30, 40, 400, 12
# contact sheet caps: tiles per run when `images` is omitted, tiles in all
PER_RUN_DEFAULT, SHEET_MAX = 4, 40
CACHES, STATUSES = ('cold', 'warm', 'apk'), ('proven', 'inferred')
RUN_ID = re.compile(r'[1-9][0-9]{0,19}')
PNG = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.png')
REPO = re.compile(r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}')
SLUG = re.compile(r'[a-z][a-z0-9-]{0,39}')
MD_URL = re.compile(r"[A-Za-z0-9._~:/?#@!$&'*+,;=%-]+")


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


MD_PUNCT = set('\\`*_{}[]()#+-.!|~')
ZWSP = '​'


def md(text, n: int = 0) -> str:
    """Free text -> inert one-line GitHub markdown: HTML special chars as entities, markdown
    punctuation (incl. `|` and backticks) backslash-escaped, and GFM autolinks defused (a zero-width
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


def validate(card: dict) -> list:
    """Check the spec's shape and sizes; return its runs normalized
    ({id, label, question, result, cache, status, images|None})."""
    if not isinstance(card, dict):
        raise ValueError('spec must be a JSON object')
    _text(card.get('title'), 'title', 256)
    if not str(card.get('title') or '').strip():
        raise ValueError('title is required')
    _text(card.get('description'), 'description', 2000)
    sections = card.get('sections') or []
    if not isinstance(sections, list) or len(sections) > SECTIONS_MAX:
        raise ValueError(f'sections must be a list of at most {SECTIONS_MAX}')
    for s in sections:
        if not isinstance(s, dict):
            raise ValueError('each section must be an object')
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
             'status': _text(r.get('status'), f'run {rid} status', 10).lower(), 'images': None}
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
        self.tests = f'https://github.com/{repo}/blob/shots/shots/{slug}/TESTS.md'

    def run_url(self, rid):
        return f'https://github.com/{self.repo}/actions/runs/{rid}'

    def run_page(self, rid):
        return f'{self.pages}/{rid}/'

    def png(self, rid, name):
        return f'{self.raw}/{rid}/{name}'


def run_line(r: dict) -> str:
    """One plain-text line for a run (escaped by each renderer)."""
    tags = ' · '.join(t.upper() if t in CACHES else t for t in (r['cache'], r['status']) if t)
    parts = [f'Q: {r["question"]}' if r['question'] else '', f'Result: {r["result"]}' if r['result'] else '', tags]
    return ' · '.join(p for p in parts if p)


def expand(card: dict, runs: list, ctx) -> dict:
    """The HTML view's card: the spec's sections + one section per run (a view of `runs`)."""
    card = dict(card)
    if ctx:
        card['url'] = ctx.page
        if any(r.get('picked') for r in runs):
            card['image'] = ctx.sheet
    sections = list(card.get('sections') or [])
    for r in runs:
        s = {'heading': r['label'], 'text': run_line(r)}
        if ctx:
            s['page'] = ctx.run_page(r['id'])
            s['images'] = [ctx.png(r['id'], i) for i in r.get('picked') or []]
            s['links'] = [['run', ctx.run_url(r['id'])], ['run card', ctx.run_page(r['id'])]]
        sections.append(s)
    card['sections'] = sections
    return card


def render(card: dict, hosts=ALLOWED_HOSTS, extra_links=()) -> str:
    """card -> HTML string. card keys: title, description, url, image (optional if a section
    has one), sections: [{heading, text, image, images, links, page}] (all optional)."""
    hosts = tuple(h.lower() for h in hosts)
    e = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    u = lambda s: e(check_url(s, hosts))  # noqa: E731
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
            '.shots{display:flex;flex-wrap:wrap;gap:8px}.shots img{max-width:240px}</style>',
            '</head>', '<body>', f'<h1>{e(title)}</h1>', f'<p>{e(card.get("description", ""))}</p>']
    if extra_links:
        out.append('<p>' + ' · '.join(f'<a href="{u(href)}">{e(text)}</a>' for text, href in extra_links) + '</p>')
    if card.get('image'):
        out.append(f'<img src="{u(card["image"])}" alt="{e(title)}">')
    for s in sections:
        out.append('<section>')
        if s.get('heading'):
            h = e(s['heading'])
            out.append(f'<h2><a href="{u(s["page"])}">{h}</a></h2>' if s.get('page') else f'<h2>{h}</h2>')
        if s.get('text'):
            out.append(f'<p>{e(s["text"])}</p>')
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


def render_md(card: dict, runs: list, ctx, hosts=ALLOWED_HOSTS) -> str:
    """The TESTS.md view (GitHub-rendered) of the same spec: title, description, sections, a table
    of every run. Links only through link() (allowlisted https); all text through md()."""
    hosts = tuple(h.lower() for h in hosts)

    def dest(href):  # allowlisted, and nothing that could end the link / table cell early
        if not MD_URL.fullmatch(check_url(href, hosts)):
            raise ValueError(f'URL has characters markdown would misread: {href!r}')
        return href
    link = lambda text, href: f'[{md(text)}]({dest(href)})'  # noqa: E731
    out = [f'# {md(card["title"], 256)}', '']
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
        out += ['| # | run | question | result | cache | status | screenshots |',
                '|---|---|---|---|---|---|---|']
        for k, r in enumerate(runs, 1):
            if ctx:
                cell = f'{link(r["label"], ctx.run_url(r["id"]))} ({link("card", ctx.run_page(r["id"]))})'
                pngs = ' '.join(link(os.path.splitext(i)[0], ctx.png(r['id'], i)) for i in r.get('picked') or [])
            else:
                cell, pngs = f'{md(r["label"])} (run {r["id"]})', ''
            out.append(f'| {k} | {cell} | {md(r["question"]) or " "} | {md(r["result"]) or " "} | '
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
    ap.add_argument('--shots-root', help='a checkout of branch shots: pick each run\'s PNGs from it')
    ap.add_argument('--md', help='also write the TESTS.md view here')
    ap.add_argument('--sheet-manifest', help='also write the contact_sheet.py --groups manifest here')
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
        elif a.shots_root or a.md or a.sheet_manifest:
            raise ValueError('--shots-root, --md and --sheet-manifest need --repo and --slug')
        view = expand(card, runs, ctx)
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
    if tests is not None:
        with open(a.md, 'w', encoding='utf-8', newline='\n') as f:
            f.write(tests)
        print(f'{a.md}: TESTS.md written ({len(runs)} runs)')
    if a.sheet_manifest:
        with open(a.sheet_manifest, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(manifest, f, indent=1)
        print(f'{a.sheet_manifest}: {sum(len(g["images"]) for g in manifest)} images in {len(manifest)} runs')
    return 0


if __name__ == '__main__':
    sys.exit(main())
