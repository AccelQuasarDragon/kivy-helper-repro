"""Public, generic privacy check for this PUBLIC repo (stdlib only).

Scans (1) every tracked file of a tree (default HEAD), CLAUDE.md included, and (2) the author /
committer emails and messages of a commit range. Exit 1 on any hit, printing file:line + rule +
a masked value (first 2 chars + ***). Exit 2 on a usage / git error.

  uv run --no-project tools/privacy_check.py                       # tree HEAD + all commits of HEAD
  uv run --no-project tools/privacy_check.py --tree X --commits 'A..B'
  uv run --no-project tools/privacy_check.py --pre-push < ref-lines   # git pre-push stdin
  python3 tools/privacy_check.py --files PATH...   # plain files outside git (devicelab output); prints file:line: rule only;
                                                   # only .privacy-allow applies there (the inline marker does not)

False positives: put `privacy-check: allow` on the line, or add `path-glob:line-regex` to
.privacy-allow (repo root, # comments): only the spans the regex matches are cleared, the rest of
the line is still scanned. Never weaken a rule.
Rules are generic on purpose: private, person-specific patterns belong in a local guard, not here.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys

ZERO = '0' * 40
MARKER = 'privacy-check: allow'
ALLOW_FILE = '.privacy-allow'

# Regex sources are written so they do not match themselves (character classes break the literal).
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
RULES = [
    ('windows-path', re.compile(r'(?<![A-Za-z0-9])[A-Z]:[\\/][A-Za-z0-9_.~$ -]')),
    ('users-path', re.compile(r'/Users/[A-Za-z0-9._-]+')),
    ('home-path', re.compile(r'/home/(?!user(?![A-Za-z0-9._-]))[A-Za-z0-9._-]+')),
    ('github-token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})')),
    ('private-key', re.compile(r'-----BEGIN[A-Z ]*PRIVATE KEY-----')),
]
NOREPLY_GH = re.compile(r'^[A-Za-z0-9._%+\[\]-]+@users\.noreply\.github\.com$', re.I)
# Identity emails GitHub itself writes (web-UI commits use noreply@github.com as committer).  # privacy-check: allow
IDENTITY_OK = {'noreply@github.com'}  # privacy-check: allow
COAUTHOR = re.compile(r'^\s*co-authored-by:', re.I)
ENV_OK = {'.env.example', '.env.sample', '.env.template'}


def git(*args, data=None):
    p = subprocess.run(['git', *args], input=data, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write(f'privacy_check: git {" ".join(args)} failed: {p.stderr.decode(errors="replace")}')
        sys.exit(2)
    return p.stdout


def mask(value):
    return value[:2] + '***'


def email_ok(addr, line):
    if NOREPLY_GH.match(addr):
        return True
    return addr.lower() == 'noreply@anthropic.com' and bool(COAUTHOR.match(line))  # privacy-check: allow


def line_hits(line, marker=True):
    """(rule, matched value) pairs for one line of text (marker=False: the inline MARKER is ignored)."""
    if marker and MARKER in line:
        return []
    hits = [('email', m.group()) for m in EMAIL.finditer(line) if not email_ok(m.group(), line)]
    for name, rx in RULES:
        hits += [(name, m.group()) for m in rx.finditer(line)]
    return hits


def load_allow(root):
    path = os.path.join(root, ALLOW_FILE)
    rules = []
    if not os.path.exists(path):
        return rules
    with open(path, encoding='utf-8') as f:
        for n, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw or raw.startswith('#'):
                continue
            glob, sep, rx = raw.partition(':')
            if not sep or not rx:
                sys.stderr.write(f'privacy_check: {ALLOW_FILE}:{n}: want path-glob:line-regex\n')
                sys.exit(2)
            rules.append((glob, re.compile(rx)))
    return rules


def strip_allowed(allow, path, line):
    """The line minus every span an allow rule for this path matched: only those exact strings are cleared,
    for every rule; whatever else is on the line is still scanned."""
    for g, rx in allow:
        if fnmatch.fnmatch(path, g):
            line = rx.sub(' ', line)
    return line


def scan_tree(rev, allow, out):
    names = git('ls-tree', '-r', '-z', '--name-only', rev).decode('utf-8', 'replace').split('\0')
    for name in filter(None, names):
        base = name.rsplit('/', 1)[-1]
        if (base == '.env' or base.startswith('.env.')) and base not in ENV_OK:
            out.append(f'{rev[:12]}:{name}: env-file tracked')
        blob = git('cat-file', 'blob', f'{rev}:{name}')
        if b'\0' in blob[:8192]:
            continue  # binary
        for n, line in enumerate(blob.decode('utf-8', 'replace').splitlines(), 1):
            for rule, val in line_hits(strip_allowed(allow, name, line)):
                out.append(f'{name}:{n}: {rule}: {mask(val)}')


def scan_files(paths, allow, out):
    """Plain files, bytes-safe (binary is scanned too: fail closed); a missing file is a hit. No value is printed."""
    for path in paths:
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            out.append(f'{path}: unreadable')
            continue
        for n, line in enumerate(data.decode('utf-8', 'replace').splitlines(), 1):
            # untrusted output (an app can log any string): the inline MARKER does not apply here
            for rule in dict.fromkeys(r for r, _ in line_hits(strip_allowed(allow, path, line), marker=False)):
                out.append(f'{path}:{n}: {rule}')


def scan_commits(revlist, allow, out):
    raw = git('log', '--format=%H%x00%ae%x00%ce%x00%B%x1e', *revlist, '--').decode('utf-8', 'replace')
    for rec in filter(None, (r.strip('\n') for r in raw.split('\x1e'))):
        sha, ae, ce, body = rec.split('\0', 3)
        for who, addr in (('author', ae), ('committer', ce)):
            if not (NOREPLY_GH.match(addr) or addr.lower() in IDENTITY_OK):
                out.append(f'commit {sha[:12]}: {who}-email: {mask(addr)}')
        for n, line in enumerate(body.splitlines(), 1):
            for rule, val in line_hits(strip_allowed(allow, f'commit:{sha}', line)):
                out.append(f'commit {sha[:12]} msg:{n}: {rule}: {mask(val)}')


def pre_push_jobs(stdin):
    """git pre-push stdin -> (trees, rev-lists) for every ref being pushed (deletes skipped)."""
    trees, ranges = [], []
    for line in stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO:
            continue
        local, remote = parts[1], parts[3]
        trees.append(local)
        known = remote != ZERO and subprocess.run(
            ['git', 'cat-file', '-e', f'{remote}^{{commit}}'], capture_output=True).returncode == 0
        ranges.append([f'{remote}..{local}'] if known else [local, '--not', '--remotes'])
    return trees, ranges


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tree', action='append', default=[], help='tree-ish to scan (repeatable; default HEAD)')
    ap.add_argument('--commits', action='append', default=[],
                    help='git log revision args, space separated, e.g. "A..B" (repeatable; default HEAD)')
    ap.add_argument('--pre-push', action='store_true', help='read git pre-push ref lines from stdin')
    ap.add_argument('--files', nargs='+', metavar='PATH', help='scan these plain files only (no git trees / commits)')
    a = ap.parse_args()
    if a.files:
        out = []
        scan_files(a.files, load_allow('.'), out)
        for line in out:
            print(line)
        print(f'privacy_check: {len(out)} hit(s); files={len(a.files)}', file=sys.stderr)
        return 1 if out else 0
    root = git('rev-parse', '--show-toplevel').decode().strip()
    os.chdir(root)
    allow = load_allow(root)
    if a.pre_push:
        trees, ranges = pre_push_jobs(sys.stdin)
    else:
        trees = a.tree or ['HEAD']
        ranges = [c.split() for c in a.commits] or [['HEAD']]
    out = []
    for t in trees:
        scan_tree(t, allow, out)
    for r in ranges:
        scan_commits(r, allow, out)
    out = list(dict.fromkeys(out))
    for line in out:
        print(line)
    print(f'privacy_check: {len(out)} hit(s); trees={len(trees)} ranges={len(ranges)}', file=sys.stderr)
    return 1 if out else 0


if __name__ == '__main__':
    sys.exit(main())
