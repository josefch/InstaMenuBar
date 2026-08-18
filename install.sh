#!/bin/bash
#
# InstaMenuBar installer.
#
#   ./install.sh
#
# Installs the SwiftBar plugin, stores your Instagram access token in the
# login Keychain, and starts SwiftBar. Existing history and config are kept.
#
set -euo pipefail

APP_DIR="$HOME/.instawatch"
PLUGIN_DIR="$HOME/Library/Application Support/SwiftBar/Plugins"
PLUGIN="instawatch.30m.py"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEYCHAIN_SERVICE="instawatch-ig-token"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
info() { printf "  %s\n" "$1"; }
ok()   { printf "\033[32m✓\033[0m %s\n" "$1"; }
fail() { printf "\033[31m✗ %s\033[0m\n" "$1" >&2; exit 1; }

[[ "$(uname)" == "Darwin" ]] || fail "macOS only."
command -v python3 >/dev/null 2>&1 || \
  fail "python3 not found — install the Xcode Command Line Tools: xcode-select --install"

bold "InstaMenuBar"
echo

mkdir -p "$APP_DIR"
chmod 700 "$APP_DIR"

# ---------------------------------------------------------------- SwiftBar ---
if [[ -d "/Applications/SwiftBar.app" ]]; then
  ok "SwiftBar already installed"
elif command -v brew >/dev/null 2>&1; then
  info "installing SwiftBar via Homebrew…"
  brew install --cask swiftbar
  ok "SwiftBar installed"
else
  fail "SwiftBar not found and Homebrew is unavailable.
    Install it from https://github.com/swiftbar/SwiftBar/releases and re-run."
fi

# ------------------------------------------------------------------ token ---
NEED_TOKEN=1
if security find-generic-password -s "$KEYCHAIN_SERVICE" -w >/dev/null 2>&1; then
  ok "an access token is already stored in your Keychain"
  read -r -p "  Replace it? [y/N] " replace
  [[ "$replace" =~ ^[Yy]$ ]] || NEED_TOKEN=0
fi

if [[ "$NEED_TOKEN" == "1" ]]; then
  bold "Paste your long-lived Instagram access token"
  info "(see README.md → 'Getting a token')"
  read -r -s -p "  Token: " TOKEN
  echo
  [[ -n "$TOKEN" ]] || fail "No token entered."

  info "verifying against graph.instagram.com…"
  RESP=$(curl -s "https://graph.instagram.com/v23.0/me?fields=username,followers_count&access_token=$TOKEN" || true)
  if echo "$RESP" | grep -q '"followers_count"'; then
    USERNAME=$(echo "$RESP" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')
    COUNT=$(echo "$RESP" | sed -n 's/.*"followers_count":\([0-9]*\).*/\1/p')
    ok "token works — @${USERNAME}, ${COUNT} followers"
  else
    echo "$RESP"
    fail "Token rejected. Check the account is Professional and that you accepted
    the Instagram Tester invitation."
  fi

  security add-generic-password -U -s "$KEYCHAIN_SERVICE" -a "$USER" -w "$TOKEN"
  ok "token stored in your login Keychain"
fi

# ----------------------------------------------------------------- config ---
if [[ ! -f "$APP_DIR/config.json" ]]; then
  cp "$SRC_DIR/config.example.json" "$APP_DIR/config.json"
  chmod 600 "$APP_DIR/config.json"
  ok "default config written to $APP_DIR/config.json"
else
  ok "existing config kept"
fi

# ----------------------------------------------------------------- plugin ---
mkdir -p "$PLUGIN_DIR"
cp "$SRC_DIR/$PLUGIN" "$PLUGIN_DIR/$PLUGIN"
chmod +x "$PLUGIN_DIR/$PLUGIN"
cp "$SRC_DIR/$PLUGIN" "$APP_DIR/$PLUGIN"
defaults write com.ameba.SwiftBar PluginDirectory "$PLUGIN_DIR"
ok "plugin installed to $PLUGIN_DIR"

# ------------------------------------------------------------- smoke test ---
info "running it once…"
if OUT=$("$PLUGIN_DIR/$PLUGIN" 2>&1); then
  FIRST=$(echo "$OUT" | head -1 | cut -d'|' -f1)
  if [[ "$FIRST" == "◎ ⚠︎"* ]]; then
    printf "\033[31m✗\033[0m ran, but the API returned an error:\n"
    echo "$OUT" | sed -n '3p'
  else
    ok "works — your menu bar will show: ${FIRST}"
  fi
else
  fail "plugin failed to run: $OUT"
fi

open -a SwiftBar 2>/dev/null || true
echo
bold "Done."
info "If SwiftBar asks for a plugin folder, choose:"
info "  $PLUGIN_DIR"
info "Enable 'Launch at Login' in SwiftBar's preferences."
info "Refresh interval = the filename: $PLUGIN → instawatch.10m.py for 10 minutes."
