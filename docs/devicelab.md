# devicelab.yml: an APK on a real phone (Firebase Test Lab, free tier)

For the author to READ AND CHECK before doing anything.
Nothing here is set up yet.
Until the 3 repo secrets below exist, the workflow does nothing: it prints a link to this page and ends green.

## Key facts first
- Firebase Test Lab (FTL) runs an APK on real phones in a Google data center.
- The free plan (Spark) gives 5 physical-device runs per day (10 virtual).
- Spark has no billing account, so nothing can be charged.
- FTL shuts down on 2027-09-30. Its successor needs billing. This workflow is a stopgap.
- Only a CRASH is evidence. A clean run on a phone that is not the reporter's disproves nothing.
- Best match for the reporter's Mi 9T (Adreno 618, Android 11): Pixel 5 (`redfin`, API 30, Adreno 620).
- Same GPU family, NOT the same driver: the Mi 9T runs Xiaomi's MIUI build of the driver.
- Devices get removed from FTL: list them before each new question (step 9).

## What the workflow does
1. `check` job: are the 3 repo secrets set? No = a "NOT SET UP" summary, green, nothing else runs.
2. It validates the inputs (same rules as inspect.yml for the artifact; device, version, taps, timeout).
3. `fetch` job (the only job with `actions: read`): downloads the APK artifact of another run of this repo.
4. It needs exactly one `.apk` with an `arm64-v8a` lib (FTL phones are arm64) and re-uploads it.
5. `test` job (the only job with `id-token: write`): logs in to Google Cloud with Workload Identity Federation.
6. No JSON key exists anywhere: GitHub hands the job a short-lived token, Google trades it for the service account.
7. It turns `taps` into a Robo script: a 20 s wait, then a tap + wait per step, then `TERMINATE_CRAWL`.
8. So Robo does not tap around the app at random after the scripted steps.
9. It runs `gcloud firebase test android run --type robo` on `device` / `version`, with `--project`.
10. It copies the results from Test Lab's default bucket (logcat, screenshots, video) into the run artifact.
11. Summary, first line: `APP OK` / `CRASH` / `APP STATE UNKNOWN`.
12. CRASH = logcat has `Fatal signal`, a `DEBUG` crash dump line, `backtrace:` or `Python for android ended`.
13. Masked in the log (GitHub `add-mask`): the project id, the service account, the project number (parsed from
    `GCP_WIF_PROVIDER` before any Google step; no `projects/<number>/` in it = the job stops there) and the
    Test Lab bucket name (once gcloud has printed it).
14. The raw gcloud output stays on the runner (`ftl.raw.log`, `copy.raw.log`: never uploaded or printed).
15. The log, the summary, `ftl.log`, `copy.log` and every uploaded result file except images / video get a
    redacted copy (`tools/ftl_redact.py`): service account -> `<redacted-sa>`, project id -> `<redacted-project>`,
    project number -> `<redacted-number>`, `test-lab-...` -> `<redacted-bucket>`.
16. Not redacted: screenshots and video (`png jpg jpeg webp mp4 webm`), and anything that names Google Cloud in
    another form. If redaction fails, nothing is uploaded and the summary says only that.

Inputs: `label`, `artifact_run` + `artifact_name` (an APK artifact of a run of THIS repo, e.g. `build-<n>` of an
inspect build), `device` (default `redfin`), `version` (default `30`), `taps` (`x,y[,wait_s]` separated by `;`,
device pixels), `timeout` (default `5m`, at most `10m`).

Free-tier limits that matter:
- Spark cannot use a custom `--results-bucket`, so the workflow never passes one.
- Results go to the default bucket Test Lab makes in the project.
- Copying from that bucket needs read access to it. Editor has it. UNVERIFIED on Spark until the first run.
- If the copy fails, the summary says `APP STATE UNKNOWN` and the results stay readable in the Firebase console (free).

## One-time setup (about 30 minutes, costs nothing on Spark)
Do the steps in order. Each says what it does and how to undo it.
Use a project id that says nothing about you (it is masked in logs, but still).

1. **Create a Firebase project.** Go to the Firebase console, "Create a project".
   - It creates a Google Cloud project too (same id). Spark (free) is the default plan.
   - Say no to Google Analytics (not needed).
   - Never click "Upgrade" / "Blaze": that is the paid plan.
   - Undo: Project settings -> General -> "Delete project" (Google keeps it 30 days, then deletes it).
2. **Open Test Lab once.** Firebase console -> your project -> Test Lab (under "Run" / "Release & Monitor").
   - Accept the terms if asked. Test Lab creates its default results bucket the first time.
3. **Enable the APIs.** Google Cloud console -> same project -> "APIs & Services" -> "Enable APIs":
   - Cloud Testing API (runs the tests).
   - Cloud Tool Results API (reads the results).
   - IAM Service Account Credentials API (Workload Identity Federation impersonates the service account with it).
   - Security Token Service API (trades the GitHub token; usually on by default).
   - Undo: "Disable API" on each.
4. **Create a service account.** IAM & Admin -> Service accounts -> "Create service account".
   - Name it e.g. `ftl-runner`. Do NOT create a key for it (we never use JSON keys).
   - Grant it the role **Editor** on the project. FTL's docs ask for Editor.
   - Narrower roles (e.g. "Firebase Test Lab Admin" + "Storage Object Viewer") are UNVERIFIED here.
   - Editor is broad, but the project holds nothing else, and only this repo's main branch can use it (step 6).
   - Undo: delete the service account.
5. **Create a Workload Identity pool.** IAM & Admin -> Workload Identity Federation -> "Create pool".
   - Name it e.g. `github`. It is the "door" GitHub's tokens come in through.
   - Undo: delete the pool (a deleted pool is kept 30 days, then removed).
6. **Add the GitHub provider to the pool.** "Add provider" -> OpenID Connect (OIDC).
   - Issuer: `https://token.actions.githubusercontent.com`.
   - Attribute mapping: `google.subject` = `assertion.sub`, `attribute.repository` = `assertion.repository`,
     `attribute.ref` = `assertion.ref`, `attribute.workflow_ref` = `assertion.workflow_ref`.
   - Attribute condition: only devicelab.yml, run from this repo's main branch, gets in (no other workflow on
     main can use the service account; the repository id stops a deleted-and-recreated repo of the same name):
     `assertion.repository=='AccelQuasarDragon/kivy-helper-repro' && assertion.repository_id=='1455407046' && assertion.ref=='refs/heads/main' && assertion.workflow_ref.startsWith('AccelQuasarDragon/kivy-helper-repro/.github/workflows/devicelab.yml@refs/heads/main')`
   - The repository id `1455407046` is this repo's (public: the `id` field of `https://api.github.com/repos/AccelQuasarDragon/kivy-helper-repro`; checked 2026-11-16).
   - Copy the provider's full name: `projects/<number>/locations/global/workloadIdentityPools/github/providers/<provider>`.
   - Undo: delete the provider.
7. **Let the pool use the service account.** Service accounts -> `ftl-runner` -> Permissions -> "Grant access".
   - Principal: `principalSet://iam.googleapis.com/projects/<number>/locations/global/workloadIdentityPools/github/attribute.repository/AccelQuasarDragon/kivy-helper-repro`
   - Role: **Workload Identity User** (`roles/iam.workloadIdentityUser`).
   - Undo: remove that principal.
8. **Set 3 repo SECRETS.** None of them is a credential, but GitHub prints a variable used in an `env:` block
   unmasked in the public log, and the provider name holds the project number. Secrets are masked.
   GitHub -> repo Settings -> Secrets and variables -> Actions -> Secrets tab -> "New repository secret":
   - `GCP_WIF_PROVIDER` = the provider's full name from step 6.
   - `GCP_SERVICE_ACCOUNT` = the service account email (`ftl-runner@<project>.iam.gserviceaccount.com`).
   - `GCP_PROJECT` = the project id.
   - Undo: delete the secrets. The workflow goes back to "NOT SET UP".
9. **List the devices** (Cloud Shell in the console, nothing to install): `gcloud firebase test android models list`
   - Look for `redfin` with API 30. If it is gone, pick another Adreno 6xx phone and pass it as `device` / `version`.
   - Never paste Cloud Shell output anywhere (it shows your Google email and project id).
     Report only "API 30: yes/no".
10. **First run:** Actions -> "device lab" -> Run workflow, with an APK artifact you already have.

## Undo everything
Delete the 3 repo secrets (step 8), then delete the Firebase project (step 1).
Deleting the project deletes the service account, the pool, the APIs and the results bucket with it.

## Privacy (public repo)
- Logs and artifacts of this public repo are readable by anyone.
- The 3 values are repo secrets, so GitHub masks each WHOLE value in the log. A part of one (the project
  number inside `GCP_WIF_PROVIDER`) is not masked by GitHub: the workflow masks it itself (What the workflow does, 13).
- The workflow redacts the project id, project number, service account email and Test Lab bucket names in the
  log, the summary and every file it uploads except images and video (13-16).
- An automatic scan then runs on everything uploaded, the file names and the summary (privacy_check rules + any raw id / number / account / bucket
  left; fails closed: nothing uploaded). Screenshots and video are NOT scanned: read them by hand (or a reviewer) after each run.
- FTL phones are Google's lab phones: their logcat has no data of yours or the reporter's.

## Design decisions (dated)
- 2026-11-16: author approved (AskUserQuestion: "yes but i need to investigate first + i want what's free"):
  free tier only, inert until set up, `id-token: write` only on the login job, WIF instead of a JSON key.
- 2026-11-16: actions pinned to tags checked on their release pages that day: `google-github-actions/auth@v3.0.0`,
  `google-github-actions/setup-gcloud@v3.0.1`. Robo script fields (`POINT_TAP`, `pointTapXCoordinate`,
  `WAIT` + `delayTime` ms, `TERMINATE_CRAWL`) checked in the FTL Robo script reference that day.
- 2026-11-16 (review): the 3 values became repo SECRETS (variables in env: blocks print unmasked), and the WIF
  condition also pins `repository_id` and the devicelab.yml `workflow_ref`.
- Not verified until the first run: the Robo script events above as FTL executes them, that the service account can read the default results bucket on Spark, and the
  exact `storage/browser/...` line gcloud prints (the copy step parses it).
