"""Entry point (p4a / desktop): one app dir, two generators chosen by config (stubkit.py).

  variant 0 (default)  showcase.py: the KivyMD 3-screen app for inspect.yml (docs/inspect.md)
  variant 1..5         bisect_app.py: the Q-B hardware bisection ladder (docs/bisect.md);
                       variants whose ui is plain Kivy never import kivymd
"""
from stubkit import load_config

if __name__ == '__main__':
    cfg = load_config()
    if cfg['variant'] > 0 or cfg['ui'] or cfg['extra']:
        from bisect_app import run
    else:
        from showcase import run
    run(cfg)
