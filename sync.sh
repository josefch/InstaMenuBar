#!/bin/bash
#
# Copy the plugin from this repo into SwiftBar's plugin folder and refresh it.
# Run after editing instawatch.30m.py.
#
# Note: SwiftBar does not run symlinked plugins — it needs a real file, which
# is why this copies rather than links.
#
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/instawatch.30m.py"
DEST_DIR="$HOME/Library/Application Support/SwiftBar/Plugins"
DEST="$DEST_DIR/instawatch.30m.py"

[[ -f "$SRC" ]] || { echo "✗ $SRC not found" >&2; exit 1; }

mkdir -p "$DEST_DIR"
rm -f "$DEST"                 # also clears a stale symlink
cp "$SRC" "$DEST"
chmod +x "$DEST"

# Ask SwiftBar to re-read it straight away rather than waiting for the interval.
open "swiftbar://refreshplugin?name=instawatch" >/dev/null 2>&1 || true

echo "✓ synced → $DEST"
