#!/usr/bin/env bash
# Drive one APK on a running emulator: install, launch, taps, a screenshot after each step,
# and the emulator's own logcat. Always exits 0: results are files, the summary step reads them.
# env: APK (path), PKG (package name), OUT (dir), TAPS ('x,y[,wait_s];...'), LAUNCH_WAIT (s),
#      SETTLE (s idle after boot + launcher focus, before install; default 10),
#      ADB_REVERSE ('P1;P2': `adb reverse tcp:P tcp:P` after install, before launch, so the app's
#      127.0.0.1:P reaches the runner's port P, e.g. a sidecar fake device; result -> OUT/adb_reverse.txt)
# OUT/system_dialogs.txt = system dialogs of OTHER apps (ANR / crash) found and how each was dismissed
# (settle, before launch, before the launch shot, before each tap); the app's own: LEFT OPEN.
# OUT/pid_at_end.txt = the app state at the end, one of: <pid(s)> | none (app gone) |
# not-installed | no-device (adb lost the emulator). Missing = this script did not finish.
set -u
mkdir -p "$OUT"
# A retry (attempt 2) reuses OUT: move the previous attempt's files to OUT/prev_attempt_<k>/ so
# its pid / errors / screenshots can never be reported as this attempt's (the static facts stay).
prev=(pid_at_end.txt errors.txt install.txt launch.txt logcat.txt logcat_clean.txt wm_size.txt
      device_sdk.txt device_fingerprint.txt system_dialogs.txt adb_reverse.txt)
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
dlog() { echo "$(date -u +%H:%M:%S) $*" >> "$OUT/system_dialogs.txt"; }
# ANR / crash dialog windows: 'Application Not Responding: <pkg>' / 'Application Error: <pkg>', one per line
dialogs() {
  adb shell dumpsys window windows 2>/dev/null | tr -d '\r' |
    grep -oE '(Application Not Responding|Application Error): [A-Za-z0-9_.]+' | sort -u || true
}
focus() { adb shell dumpsys window 2>/dev/null | tr -d '\r' | grep -m1 -oE 'mCurrentFocus=.*' | cut -c1-160 || true; }
# tap_id RESOURCE_ID: tap the centre of that view (uiautomator dump); exit 0 = tapped
tap_id() {
  local b x1 y1 x2 y2
  adb shell uiautomator dump /sdcard/stub_ui.xml >/dev/null 2>&1 || return 1
  b=$(adb shell cat /sdcard/stub_ui.xml 2>/dev/null | tr -d '\r' |
      grep -oE "resource-id=\"$1\"[^>]*bounds=\"\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]\"" | head -1 |
      sed -E 's/.*bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/\1 \2 \3 \4/')
  [ -n "$b" ] || return 1
  read -r x1 y1 x2 y2 <<< "$b"
  adb shell input tap $(((x1 + x2) / 2)) $(((y1 + y2) / 2))
}
# clear_dialogs WHERE: dismiss OTHER apps' ANR / crash dialogs (e.g. "Pixel Launcher isn't responding"
# after boot, which covered the launch shot and ate the first tap). Up to 3 methods; before EACH one the
# dialog list is re-read and the app's OWN dialog is never touched (it is a result). BACK only when the
# FOCUSED window is another app's dialog: BACK on our app would close it (Kivy exit_on_escape).
# Bound: about 15 s per call (3 x (dumpsys + method + 2 s)).
clear_dialogs() {
  local where=$1 d e method f last='' found=0
  for method in broadcast button back final; do
    mapfile -t d < <(dialogs)
    if [ "${#d[@]}" -eq 0 ]; then
      [ -z "$last" ] || dlog "$where: dismissed by $last"
      return 0
    fi
    for e in "${d[@]}"; do
      if [ "${e##*: }" = "$PKG" ]; then
        dlog "$where: ${d[*]} (includes the app's own: LEFT OPEN, it is a result)"
        return 0
      fi
    done
    [ "$found" = 1 ] || { dlog "$where: found ${d[*]}"; found=1; }
    case "$method" in
      broadcast) adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS >/dev/null 2>&1 ;;
      # ANR dialog: 'Wait' (the other app keeps running); crash dialog: 'Close app'
      button) tap_id android:id/aerr_wait || tap_id android:id/aerr_close ;;
      back)
        f=$(focus)
        if [[ "$f" =~ Application\ (Not\ Responding|Error):\ ([A-Za-z0-9_.]+) ]] && [ "${BASH_REMATCH[2]}" != "$PKG" ]; then
          adb shell input keyevent KEYCODE_BACK
        else
          dlog "$where: BACK not sent (focus: ${f:-none}): left"
        fi ;;
      final)
        dlog "$where: STILL OPEN after broadcast, button, back: ${d[*]}"
        echo "$where: system dialog still open: ${d[*]}" >> "$OUT/errors.txt"
        return 0 ;;
    esac
    last=$method
    sleep 2
  done
}
# settle: boot completed, then the launcher focused (at most 3 clear_dialogs rounds meanwhile), then
# SETTLE s idle. Real bound: 60 s (boot) + 60 s (focus polls) + 3 x ~15 s (dialogs) + SETTLE: ~3 min + SETTLE.
settle() {
  local i f='' rounds=0
  for i in $(seq 1 30); do
    [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] && break
    sleep 2
  done
  for i in $(seq 1 30); do
    f=$(focus)
    # the launcher's OWN window (an ANR dialog title names the launcher package too)
    if grep -qi launcher <<< "$f" && ! grep -qE 'Application (Not Responding|Error): ' <<< "$f"; then break; fi
    if [ "$rounds" -lt 3 ]; then clear_dialogs "settle"; rounds=$((rounds + 1)); fi
    sleep 2
  done
  dlog "settle: ${f:-no mCurrentFocus} (check $i of 30, $rounds dialog round(s)); then idle ${SETTLE:-10} s"
  sleep "${SETTLE:-10}"
}
adb wait-for-device
adb shell wm size > "$OUT/wm_size.txt" 2>&1
adb shell getprop ro.build.version.sdk > "$OUT/device_sdk.txt" 2>&1
adb shell getprop ro.build.fingerprint > "$OUT/device_fingerprint.txt" 2>&1
adb logcat -c || true
adb logcat -v threadtime > "$OUT/logcat.txt" 2>&1 &
lc=$!
: > "$OUT/system_dialogs.txt"
settle
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
  # ports validated by inspect.yml's check job (digits, 1-65535); re-checked here
  IFS=';' read -r -a rports <<< "${ADB_REVERSE:-}"
  for p in "${rports[@]}"; do
    p=$(echo "$p" | tr -d ' ')
    [ -n "$p" ] || continue
    if [[ "$p" =~ ^[0-9]{1,5}$ ]] && adb reverse "tcp:$p" "tcp:$p" >/dev/null 2>&1; then
      echo "tcp:$p -> tcp:$p ok" >> "$OUT/adb_reverse.txt"
    else
      echo "tcp:$p FAILED" >> "$OUT/adb_reverse.txt"
      echo "adb reverse tcp:$p failed" >> "$OUT/errors.txt"
    fi
  done
  [ ! -s "$OUT/adb_reverse.txt" ] || adb reverse --list >> "$OUT/adb_reverse.txt" 2>&1
  clear_dialogs 'before launch'
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 > "$OUT/launch.txt" 2>&1
  sleep "${LAUNCH_WAIT:-30}"
  clear_dialogs 'before the launch shot'
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
    clear_dialogs "before tap $x,$y"
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
