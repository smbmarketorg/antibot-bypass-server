#!/bin/sh
set -eu

export DISPLAY="${DISPLAY:-:99}"

Xvfb "$DISPLAY" -screen 0 1920x1080x24 -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
xvfb_pid=$!

i=0
while [ "$i" -lt 50 ]; do
  if kill -0 "$xvfb_pid" 2>/dev/null; then
    if [ -S "/tmp/.X11-unix/X${DISPLAY#:}" ]; then
      break
    fi
  else
    echo "Xvfb failed to start on $DISPLAY" >&2
    cat /tmp/xvfb.log >&2 || true
    exit 1
  fi
  i=$((i + 1))
  sleep 0.1
done

if ! kill -0 "$xvfb_pid" 2>/dev/null; then
  echo "Xvfb exited before the API started" >&2
  cat /tmp/xvfb.log >&2 || true
  exit 1
fi

if [ ! -S "/tmp/.X11-unix/X${DISPLAY#:}" ]; then
  echo "Xvfb did not open display $DISPLAY" >&2
  cat /tmp/xvfb.log >&2 || true
  exit 1
fi

exec "$@"
