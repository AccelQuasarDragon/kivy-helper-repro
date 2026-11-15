#!/usr/bin/env bash
# Drive one APK on a running emulator: install, launch, taps, a screenshot after each step,
# and the emulator's own logcat. Always exits 0: results are files, the summary step reads them.
# env: APK (path), PKG (package name), OUT (dir), TAPS ('x,y[,wait_s];...'), LAUNCH_WAIT (s)
# OUT/pid_at_end.txt = the app state at the end, one of: <pid(s)> | none (app gone) |
# not-installed | no-device (adb lost the emulator). Missing = this script did not finish.
set -u
mkdir -p "$OUT"
# A retry (attempt 2) reuses OUT: move the previous attempt's files to OUT/prev_attempt_<k>/ so
# its pid / errors / screenshots can never be reported as this attempt's (the static facts stay).
prev=(pid_at_end.txt errors.txt install.txt launch.txt logcat.txt logcat_clean.txt wm_size.txt
      device_sdk.txt device_fingerprint.txt)
found=0
for f in "${prev[@]}"; do [ -e "$OUT/$f" ] && found=1; done
for f in "$OUT"/*.png; do [ -e "$f" ] && found=1; done
if [ "$found" = 1 ]; then
  k=1; while [ -e "$OUT/prev_attempt_$k" ]; do k=$((k + 1)); done
  mkdir -p "$OUT/prev_attempt_$k"
  for f in "${prev[@]}"; do [ ! -e "$OUT/$f" ] || mv "$OUT/$f" "$OUT/prev_attempt_$k/"; done
  for f in "$OUT"/*.png; do [ ! -e "$f" ] || mv "$f" "$OUT/prev_attempt_$k/"; done
fi
alive() { [ "$(adb get-state 2>/dev/null | tr -d '\r')" = 'device' ]; }
adb wait-for-device
adb shell wm size > "$OUT/wm_size.txt" 2>&1
adb shell getprop ro.build.version.sdk > "$OUT/device_sdk.txt" 2>&1
adb shell getprop ro.build.fingerprint > "$OUT/device_fingerprint.txt" 2>&1
adb logcat -c || true
adb logcat -v threadtime > "$OUT/logcat.txt" 2>&1 &
lc=$!
n=0
shot() {  # shot NAME -> OUT/NN_NAME.png
  local f
  f=$(printf '%s/%02d_%s.png' "$OUT" "$n" "$1")
  adb exec-out screencap -p > "$f" 2>/dev/null || echo "screencap failed: $f" >> "$OUT/errors.txt"
  [ -s "$f" ] || rm -f "$f"
  n=$((n + 1))
}
if ! adb install -r -g "$APK" > "$OUT/install.txt" 2>&1; then
  echo 'install failed' >> "$OUT/errors.txt"
  if alive; then echo 'not-installed' > "$OUT/pid_at_end.txt"; else echo 'no-device' > "$OUT/pid_at_end.txt"; fi
else
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 > "$OUT/launch.txt" 2>&1
  sleep "${LAUNCH_WAIT:-30}"
  shot launch
  IFS=';' read -r -a steps <<< "${TAPS:-}"
  for step in "${steps[@]}"; do
    step=$(echo "$step" | tr -d ' ')
    [ -n "$step" ] || continue
    if ! [[ "$step" =~ ^([0-9]+),([0-9]+)(,([0-9]+(\.[0-9]+)?))?$ ]]; then
      echo "bad tap step (want x,y[,wait_s]): $step" >> "$OUT/errors.txt"
      continue
    fi
    x=${BASH_REMATCH[1]}; y=${BASH_REMATCH[2]}; w=${BASH_REMATCH[4]:-5}
    adb shell input tap "$x" "$y"
    sleep "$w"
    shot "tap_${x}_${y}"
  done
  if alive; then
    pid=$(adb shell pidof "$PKG" 2>/dev/null | tr -d '\r')
    echo "${pid:-none}" > "$OUT/pid_at_end.txt"
  else
    echo 'no-device' > "$OUT/pid_at_end.txt"
  fi
fi
sleep 2
kill "$lc" 2>/dev/null || true
exit 0
