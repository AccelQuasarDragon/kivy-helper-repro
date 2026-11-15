# kivy-helper-repro

Reproduce "my buildozer build broke" reports on GitHub Actions instead of a local machine.

**Actions → buildozer repro → Run workflow**, fill the form:

| Input | Meaning |
|---|---|
| label | what question this run answers (shows in the run name) |
| runner | build host: `ubuntu-latest` (x86_64) or `ubuntu-24.04-arm` |
| image | buildozer container, default `ghcr.io/kivy/buildozer:latest` |
| requirements / p4a_branch / archs | the usual spec keys |
| extra | more overrides, `;` separated: `android.api=36;android.ndk=29` |
| command | buildozer command, default `android debug` |
| repo / ref / app | build a public GitHub repo (or an app dir of this repo, default `stub`) |
| add_archs | archs appended if missing (`x86_64` for an emulator) |
| app_config | JSON baked into the app as `app_config.json` |
| cache / apk_cache | build caches (only `off` runs are evidence) / reuse an identical built APK |

The spec is the image's own `buildozer init` default plus your overrides
(`tools/patch_spec.py`), so every run starts from a clean, known spec.
The run summary shows the host arch, the image digest, the pip versions seen and
the log lines before the first error; `build.log`, the spec and any APK are
uploaded as an artifact (14 days).

What a run does NOT match: the reporter's own `.buildozer` / `~/.buildozer`
leftovers (runs always start clean) and rootless podman vs docker details.

**Actions -> inspect apk**: static facts of an APK plus an optional headless emulator run with
screenshots (software rendering: no GPU bugs). See [docs/inspect.md](docs/inspect.md).
