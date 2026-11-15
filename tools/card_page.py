"""Generate ONE static HTML card page (Open Graph + Twitter tags) so a link pasted in Discord
unfurls as a rich embed: title + description + one big image. Stdlib only.

One generator, two modes (docs/cards.md):
- run card: one section (a run's title, one-line result, contact sheet, per-PNG images, links)
- report card: several sections (one per run), og:image = the first section's image (or --image)

Every text value is html.escape'd (quote=True); every URL must be https on an allowed host.
The og:description is cut to 200 chars (Discord truncates longer ones anyway).

CLI (run card):
  card_page.py OUT.html --title T --description D --image SHEET_URL --url PAGE_URL \
      [--img PNG_URL ...] [--link 'text=URL' ...] [--allow-host HOST ...]
CLI (any card, incl. a report) from a JSON spec:
  card_page.py OUT.html --spec card.json [--allow-host HOST ...]
  spec = {"title", "description", "image", "url",
          "sections": [{"heading", "text", "image", "images": [...], "links": [[text, url], ...],
                        "page": url}]}
  (a report spec has several sections; "image" may be omitted = the first section's image)
Locally: uv run --no-project tools/card_page.py ...
Exit codes: 0 written, 2 bad input (bad URL, malformed spec, missing key); argparse errors are 2 too.
Pass free text in the `=` form (--title="$LABEL") so a value like `--help` is not read as an option.
"""
import argparse
import html
import json
import sys
from urllib.parse import urlsplit

ALLOWED_HOSTS = ('raw.githubusercontent.com', 'github.com', 'accelquasardragon.github.io')
DESC_MAX = 200
THEME = '#2b6cb0'


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


def render(card: dict, hosts=ALLOWED_HOSTS) -> str:
    """card -> HTML string. card keys: title, description, url, image (optional if a section
    has one), sections: [{heading, text, image, images, links, page}] (all optional)."""
    hosts = tuple(h.lower() for h in hosts)
    e = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    u = lambda s: e(check_url(s, hosts))  # noqa: E731
    sections = card.get('sections') or []
    image = card.get('image') or next((s['image'] for s in sections if s.get('image')), None)
    if not image:
        raise ValueError('card needs an image (card.image or a section image)')
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


def write(path: str, card: dict, hosts=ALLOWED_HOSTS) -> None:
    page = render(card, hosts)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(page)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('out')
    ap.add_argument('--spec', help='JSON card spec (any mode, incl. a multi-run report)')
    ap.add_argument('--title')
    ap.add_argument('--description', default='')
    ap.add_argument('--image', help='og:image: absolute https URL (the contact sheet)')
    ap.add_argument('--url', help='og:url: the page\'s own URL')
    ap.add_argument('--img', action='append', default=[], help='a per-PNG image URL (repeat)')
    ap.add_argument('--link', action='append', default=[], help="'text=URL' (repeat)")
    ap.add_argument('--allow-host', action='append', default=[], help='extra allowed host (e.g. a fork\'s Pages host)')
    a = ap.parse_args()
    hosts = ALLOWED_HOSTS + tuple(a.allow_host)
    if a.spec:
        try:
            with open(a.spec, encoding='utf-8') as f:
                card = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f'card_page: cannot read spec {a.spec!r}: {exc}', file=sys.stderr)
            return 2
        if not isinstance(card, dict):
            print('card_page: spec must be a JSON object', file=sys.stderr)
            return 2
    else:
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
    try:
        write(a.out, card, hosts)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        # bad values or a malformed spec (wrong types / shapes): one clean line, exit 2
        print(f'card_page: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    print(f'{a.out}: card page written')
    return 0


if __name__ == '__main__':
    sys.exit(main())
