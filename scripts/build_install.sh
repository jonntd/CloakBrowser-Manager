#!/usr/bin/env bash
# Build the Tauri app and install it into /Applications, replacing the
# running instance in one step.
#
# Usage:
#   scripts/build_install.sh            # full release build + install + relaunch
#   scripts/build_install.sh --skip-build   # install the last built bundle only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="CloakAccounts.app"
BUNDLE="$ROOT/src-tauri/target/release/bundle/macos/$APP_NAME"
DEST="/Applications/$APP_NAME"
BIN="cloak-accounts"

cd "$ROOT"
if [[ "${1:-}" != "--skip-build" ]]; then
  echo "==> Building release bundle…"
  cargo tauri build
fi

if [[ ! -d "$BUNDLE" ]]; then
  echo "error: bundle not found at $BUNDLE (run without --skip-build first)" >&2
  exit 1
fi

echo "==> Quitting $APP_NAME if running…"
pkill -f "/Applications/$APP_NAME/Contents/MacOS/$BIN" 2>/dev/null || true
sleep 1

echo "==> Installing to ${DEST}…"
rm -rf "$DEST"
ditto "$BUNDLE" "$DEST"

echo "==> Launching…"
open "$DEST"
sleep 2
pgrep -fl "$BIN" >/dev/null && echo "✔ Installed and running." || {
  echo "warning: app did not appear to start; launch it manually." >&2
  exit 1
}
