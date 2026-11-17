#!/usr/bin/env bash
# Run: bash tests/inject_test.sh            (PYTHON=/path/to/python3 to pick the interpreter; default python3)
#
# Regression guard for build.yml's "Make spec" step: a crafted repo-root buildozer.spec must never
# put more than ONE line into GITHUB_ENV (a second line = an extra env var for later host steps, e.g.
# BASH_ENV), must fall back to `buildozer init` when its source.dir is unsafe / unreadable, and must be
# used (copied, source.dir = .) when its source.dir is the app dir.
# How: the step's real `run:` script is cut out of build.yml (awk, no YAML library) and run in bash
# with docker / sudo stubbed (docker "init" writes a minimal spec), once per crafted spec, in a
# mktemp dir (nothing is written anywhere else). Exit 0 = all pass, 1 = a failure.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)
PYTHON=${PYTHON:-python3}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# the `run: |` block of the step named "Make spec ...", indentation (10 spaces) removed
awk '
  /^      - name: Make spec/ { in_step = 1; next }
  in_step && /^      - / { exit }
  in_step && /^        run: \|/ { in_run = 1; next }
  in_run { sub(/^          /, ""); print }
' "$REPO_ROOT/.github/workflows/build.yml" > "$TMP/step.sh"
[ -s "$TMP/step.sh" ] || { echo 'FAIL could not extract the Make spec step from build.yml'; exit 1; }

cat > "$TMP/stubs.sh" <<'EOF'
sudo() { [ "$1" = chmod ] && return 0; "$@"; }
docker() { echo 'DOCKER (init stub)'; printf '[app]\ntitle = init\n' > work/buildozer.spec; }
python3() { "$PYTHON" "$@"; }
EOF

pass=0; fail=0
# run_case NAME SPEC_BYTES(printf %b) EXPECTED_TEXT_IN_BASE_SPEC
run_case() {
  local d="$TMP/case_$1" rc lines
  mkdir -p "$d/src/src"
  printf 'print("hi")\n' > "$d/src/src/main.py"
  printf '%b' "$2" > "$d/src/buildozer.spec"
  cp -r "$REPO_ROOT/tools" "$d/"
  : > "$d/genv.txt"
  (cd "$d" && export PYTHON REPO=x/y APP=src APP_DIR=src/src EXTRA= ADD_ARCHS= REQUIREMENTS= P4A_BRANCH= ARCHS= \
     APP_CONFIG= IMAGE=img GITHUB_ENV="$d/genv.txt" &&
     bash -c "set -eo pipefail; source '$TMP/stubs.sh'; source '$TMP/step.sh'" > "$d/out.txt" 2>&1)
  rc=$?
  lines=$(wc -l < "$d/genv.txt" | tr -d ' ')
  if [ "$rc" = 0 ] && [ "$lines" = 1 ] && grep -q '^BASE_SPEC=' "$d/genv.txt" && grep -qF -- "$3" "$d/genv.txt" &&
     ! grep -qE 'BASH_ENV|NODE_OPTIONS' "$d/genv.txt"; then
    echo "PASS $1: $(cut -c1-150 "$d/genv.txt")"; pass=$((pass + 1))
  else
    echo "FAIL $1 (exit $rc, $lines GITHUB_ENV line(s)):"; sed 's/^/   env: /' "$d/genv.txt"; tail -5 "$d/out.txt" | sed 's/^/   log: /'
    fail=$((fail + 1))
  fi
}
INIT='buildozer init'
run_case inject_mismatch  '[app]\ntitle = t\nsource.dir = x\n    BASH_ENV=/tmp/e.sh\n' 'source.dir=(unsafe value)'
run_case inject_match     '[app]\nsource.dir = src\n  NODE_OPTIONS=--require=/tmp/x.js\n' 'source.dir=(unsafe value)'
run_case unreadable       'no section header\nsource.dir = src\n' 'could not be read'
run_case shell_chars      '[app]\nsource.dir = src;touch /tmp/pwn\n' 'source.dir=(unsafe value)'
run_case u2028            '[app]\nsource.dir = src\xe2\x80\xa8BASH_ENV=/tmp/e.sh\n' 'source.dir=(unsafe value)'
run_case u0085            '[app]\nsource.dir = src\xc2\x85BASH_ENV=/tmp/e.sh\n' 'source.dir=(unsafe value)'
run_case cr_only          '[app]\rsource.dir = x\r    BASH_ENV=/tmp/e.sh\r' 'source.dir=(unsafe value)'
run_case interpolation    '[app]\nfoo = src\nsource.dir = %%(foo)s\n' 'source.dir=(unsafe value)'
run_case dup_traversal    '[app]\nsource.dir = src\nsource.dir = ../../etc\n' "$INIT"
run_case invalid_utf8     '[app]\nsource.dir = src\xff\n' 'could not be read'
run_case dotdot_accepted  '[app]\nsource.dir = src/../src\n' 'repo root buildozer.spec (source.dir=src/../src)'
run_case match_warn       '[app]\nsource.dir = src\nicon.filename = data/icon.png\np4a.local_recipes = recipes\npresplash.filename = %%(source.dir)s/p.png\n' 'paths not rewritten: p4a.local_recipes icon.filename'
run_case match_clean      '[app]\nsource.dir = src\n' 'repo root buildozer.spec (source.dir=src)'
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
