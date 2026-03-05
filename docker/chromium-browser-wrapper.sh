#!/bin/sh

exec /usr/bin/chromium-browser.real \
  --no-sandbox \
  --disable-setuid-sandbox \
  --disable-dev-shm-usage \
  "$@"
