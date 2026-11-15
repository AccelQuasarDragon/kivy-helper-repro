#!/usr/bin/env bash
# Drive one APK on a running emulator: install, launch, taps, a screenshot after each step,
# and the emulator's own logcat. Always exits 0: results are files, the summary step reads them.
# env: APK (path), PKG (package name), OUT (dir), TAPS ('x,y[,wait_s];...'), LAUNCH_WAIT (s)
set -u
mkdir -p "$OUT"
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
  pid=$(adb shell pidof "$PKG" 2>/dev/null | tr -d '\r')
  echo "${pid:-none}" > "$OUT/pid_at_end.txt"
fi
sleep 2
kill "$lc" 2>/dev/null || true
exit 0
