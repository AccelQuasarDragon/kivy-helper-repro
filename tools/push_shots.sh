#!/usr/bin/env bash
# Publish the files of SRC_DIR to shots/<DEST>/ on the orphan branch `shots` (served by GitHub Pages).
# Shared by inspect.yml (shots job: DEST = <run_id>) and report.yml (publish job: DEST = <slug>).
# usage: push_shots.sh SRC_DIR DEST [overwrite|no-overwrite|check]
#   check = only fetch the branch tip and exit 3 if shots/<DEST> exists, else 0 (nothing pushed; report.yml
#           runs it before pushing phone media, so an existing slug is refused before anything is written)
# env: TOKEN (the job's GITHUB_TOKEN, contents: write), GITHUB_REPOSITORY;
#      SHOTS_REMOTE (optional: another remote URL / path, for local tests)
# exit 0 = pushed (check: DEST is free); 3 = DEST exists and no-overwrite / check; 1 = gave up after all attempts.
#
# Race-safe by construction: many runs may finish together (5 gate runs raced on 2026-11-15:
# "rejected (fetch first)" then "cannot lock ref"). Each attempt starts from a FRESH fetch of the
# branch tip, re-copies the files and commits on top of it (every run writes its own folder, so
# there is nothing to merge), then pushes; ANY push failure is retried with jittered back-off.
# No `concurrency:` group on purpose: GitHub keeps only ONE pending job per group and CANCELS the
# older pending ones, which would silently drop a run's shots.
set -u
src=$1; dest=$2; mode=${3:-overwrite}
case "$mode" in overwrite|no-overwrite|check) ;; *) echo "::error::push_shots: bad mode '$mode'"; exit 1 ;; esac
[[ "$dest" =~ ^[A-Za-z0-9-]{1,64}$ ]] || { echo "::error::push_shots: bad DEST '$dest'"; exit 1; }
[ -d "$src" ] || { echo "::error::push_shots: no dir $src"; exit 1; }
src=$(cd "$src" && pwd)
url=${SHOTS_REMOTE:-"https://x-access-token:${TOKEN:-}@github.com/${GITHUB_REPOSITORY:-}.git"}
work=$(mktemp -d)
attempts=10
for i in $(seq 1 "$attempts"); do
  cd "$work" && rm -rf "$work/repo"
  git init -q "$work/repo"
  cd "$work/repo" || exit 1
  git config core.autocrlf false  # PNGs byte-exact on any OS
  git config user.name 'github-actions[bot]'
  git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
  git remote add origin "$url"
  if git ls-remote --exit-code origin refs/heads/shots >/dev/null 2>&1; then
    git fetch -q --depth 1 origin shots || { echo "attempt $i: fetch failed"; sleep $((i * 2 + RANDOM % 5)); continue; }
    git checkout -q -b shots FETCH_HEAD
  else
    git checkout -q --orphan shots
    printf '# shots\nScreenshots + card pages pushed by inspect.yml / report.yml runs (shots/<id>/). Orphan branch: no code.\n' > README.md
    git add README.md
  fi
  if [ "$mode" != overwrite ] && [ -e "shots/$dest" ]; then
    echo "::error::shots/$dest already exists on branch shots (set overwrite to replace it)"
    exit 3
  fi
  if [ "$mode" = check ]; then echo "shots/$dest is free"; exit 0; fi
  # Pages serves the branch as-is (no Jekyll build) when .nojekyll exists at its root
  [ -f .nojekyll ] || { : > .nojekyll; git add .nojekyll; }
  rm -rf "shots/$dest"
  mkdir -p "shots/$dest"
  cp -R "$src"/. "shots/$dest/"
  git add -A "shots/$dest"
  if git diff --cached --quiet; then echo "shots/$dest: nothing changed"; exit 0; fi
  git commit -q -m "shots/$dest"
  if git push -q origin HEAD:shots 2>"$work/push_err.txt"; then
    echo "pushed shots/$dest (attempt $i)"
    exit 0
  fi
  echo "attempt $i/$attempts: push failed: $(tr '\n' ' ' < "$work/push_err.txt" | sed 's/x-access-token:[^@]*@/x-access-token:***@/g' | cut -c1-300)"
  sleep $((i * 2 + RANDOM % 7))  # jittered back-off: the racers spread out
done
echo "::error::push to shots failed after $attempts attempts"
exit 1
