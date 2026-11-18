# Run: uv run --no-project tests/test_publish_order.py      (needs bash + git; BASH=/path/to/bash to pick one)
"""Regression guard for report.yml's publish step + tools/push_shots.sh (temp dirs and a local bare repo
only, via SHOTS_REMOTE; nothing is pushed anywhere else). The step's real `run:` script is cut out of
report.yml (text scan, no YAML library) and run in bash:
- push_shots.sh `check`: exit 3 when shots/<dest> exists, 0 when free, and pushes nothing; a bad mode = exit 1;
- an existing slug without overwrite is refused BEFORE any phone media is pushed;
- a failed media push leaves no report behind, and re-running the same step converges (media + report);
- re-pushing identical media is a no-op (overwrite, "nothing changed").
Exit 0 = all pass, 1 = a failure."""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
BASH = os.environ.get('BASH_BIN') or os.environ.get('BASH') or shutil.which('bash') or 'bash'
FAILS = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f' ({detail})' if detail and not cond else ''))
    if not cond:
        FAILS.append(name)


def step_script() -> str:
    lines = open(os.path.join(ROOT, '.github', 'workflows', 'report.yml'), encoding='utf-8').read().splitlines()
    k = next(i for i, x in enumerate(lines) if x.strip().startswith('- name: Push to branch shots (phone media'))
    k = next(i for i in range(k, len(lines)) if lines[i].strip() == 'run: |')
    ind = len(lines[k + 1]) - len(lines[k + 1].lstrip())
    out = []
    for x in lines[k + 1:]:
        if x.strip() and len(x) - len(x.lstrip()) < ind:
            break
        out.append(x[ind:])
    return '\n'.join(out) + '\n'


def tree(remote) -> set:
    r = subprocess.run(['git', '--git-dir', remote, 'ls-tree', '-r', '--name-only', 'shots'], capture_output=True, text=True)
    return set(r.stdout.split()) if r.returncode == 0 else set()


def main():
    script = step_script()
    with tempfile.TemporaryDirectory() as tmp:
        remote = os.path.join(tmp, 'remote.git')
        subprocess.run(['git', 'init', '-q', '--bare', remote], check=True)
        work = os.path.join(tmp, 'work')
        os.makedirs(os.path.join(work, 'tools'))
        shutil.copy(os.path.join(ROOT, 'tools', 'push_shots.sh'), os.path.join(work, 'tools', 'push_shots.sh'))
        with open(os.path.join(work, 'step.sh'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(script)

        def put(path, data):
            p = os.path.join(work, path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8', newline='\n') as f:
                f.write(data)

        def run(args=None, **env):
            e = dict(os.environ, SHOTS_REMOTE=remote.replace('\\', '/'), TOKEN='', GITHUB_REPOSITORY='o/r',
                     GITHUB_STEP_SUMMARY=os.path.join(work, 'summary.md'), OVERWRITE='false', IDS='')
            e.update(env)
            r = subprocess.run([BASH] + (args or ['step.sh']), cwd=work, env=e, capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr

        put('pub/index.html', 'report 1')
        put('media/202/0.png', 'png bytes')
        rc, out = run(SLUG='rep', IDS='202')
        t = tree(remote)
        check('fresh: media + report pushed', rc == 0 and {'shots/202/0.png', 'shots/rep/index.html'} <= t, f'rc={rc} {t} {out[-300:]}')

        rc, out = run(['tools/push_shots.sh', 'pub', 'rep', 'check'])
        check('push_shots check: existing dest -> exit 3', rc == 3, f'rc={rc}')
        before = tree(remote)
        rc, out = run(['tools/push_shots.sh', 'pub', 'free-one', 'check'])
        check('push_shots check: free dest -> exit 0, nothing pushed', rc == 0 and tree(remote) == before, f'rc={rc}')
        rc, out = run(['tools/push_shots.sh', 'pub', 'x', 'bogus'])
        check('push_shots: bad mode -> exit 1', rc == 1, f'rc={rc}')

        put('media/303/0.png', 'other')
        rc, out = run(SLUG='rep', IDS='303')
        check('slug exists (no overwrite): refused (3) before any media push',
              rc == 3 and not any(x.startswith('shots/303/') for x in tree(remote)), f'rc={rc} {out[-300:]}')

        put('pub/index.html', 'report 2')
        rc, out = run(SLUG='rep2', IDS='404')  # media/404 missing: its push fails
        t = tree(remote)
        check('media push failed: no report pushed', rc == 1 and 'shots/rep2/index.html' not in t, f'rc={rc} {t}')
        put('media/404/0.png', 'fixed')
        rc, out = run(SLUG='rep2', IDS='404')
        t = tree(remote)
        check('re-run converges: media + report pushed', rc == 0 and {'shots/404/0.png', 'shots/rep2/index.html'} <= t, f'rc={rc} {out[-300:]}')

        head = subprocess.run(['git', '--git-dir', remote, 'rev-parse', 'shots'], capture_output=True, text=True).stdout
        rc, out = run(SLUG='rep3', IDS='202')
        t = tree(remote)
        check('identical media re-pushed: no-op for shots/202/, report pushed',
              rc == 0 and 'shots/202: nothing changed' in out and 'shots/rep3/index.html' in t, f'rc={rc} {out[-300:]}')
        check('history grew by the report commit only', subprocess.run(
            ['git', '--git-dir', remote, 'rev-list', '--count', f'{head.strip()}..shots'], capture_output=True, text=True).stdout.strip() == '1')
    print(f'{len(FAILS)} failure(s)')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
