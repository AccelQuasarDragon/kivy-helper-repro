# Run: uv run --no-project tests/test_workflow_form.py
"""Regression guard: card_page.workflow_form() (its own targeted parser) must return exactly the
workflow_dispatch input names of inspect.yml and build.yml, in form order, with their defaults.
The reference is read here by a SECOND, independent method: PyYAML when it is importable, else a
line scan of the `inputs:` block (stdlib only). Exit 0 = all pass, 1 = drift."""
import importlib.util
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
spec = importlib.util.spec_from_file_location('card_page', os.path.join(ROOT, 'tools', 'card_page.py'))
card_page = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card_page)


def reference(wf: str) -> dict:
    path = os.path.join(ROOT, '.github', 'workflows', wf)
    try:
        import yaml  # noqa: PLC0415 - optional
    except ImportError:
        yaml = None
    if yaml:
        with open(path, encoding='utf-8') as f:
            doc = yaml.safe_load(f)
        on = doc.get('on', doc.get(True))
        inputs = on['workflow_dispatch']['inputs']
        out = {}
        for k, v in inputs.items():
            d = (v or {}).get('default', '')
            out[k] = ('true' if d else 'false') if isinstance(d, bool) else str(d)
        return out
    # stdlib fallback: names only (defaults are then compared by count of names)
    text = open(path, encoding='utf-8').read()
    block = text.split('  workflow_dispatch:\n', 1)[1].split('\n  workflow_call:', 1)[0].split('\nrun-name:', 1)[0]
    return {m: None for m in re.findall(r'^ {6}([a-z][a-z0-9_]*):\s*$', block, re.M)}


def main() -> int:
    ok = True
    for wf in ('inspect.yml', 'build.yml'):
        name, form = card_page.workflow_form(wf)
        ref = reference(wf)
        same_names = list(form) == list(ref)
        same_defaults = all(v is None or form.get(k) == v for k, v in ref.items())
        print(f'{"PASS" if same_names else "FAIL"} {wf}: {len(form)} input names, same names + order as the reference')
        print(f'{"PASS" if same_defaults else "FAIL"} {wf}: defaults match the reference'
              + ('' if any(v is not None for v in ref.values()) else ' (PyYAML not installed: names only)'))
        if not same_names:
            print('   form:', list(form), '\n   ref: ', list(ref))
        ok = ok and same_names and same_defaults and bool(name)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
