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

The spec is the image's own `buildozer init` default plus your overrides
(`tools/patch_spec.py`), so every run starts from a clean, known spec.
The run summary shows the host arch, the image digest, the pip versions seen and
the log lines before the first error; `build.log`, the spec and any APK are
uploaded as an artifact (14 days).

What a run does NOT match: the reporter's own `.buildozer` / `~/.buildozer`
leftovers (runs always start clean) and rootless podman vs docker details.
