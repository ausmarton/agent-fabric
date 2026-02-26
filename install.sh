#!/usr/bin/env sh
# install.sh — one-liner installer for the agentic-concierge launcher binary.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ausmarton/agentic-concierge/main/install.sh | sh
#
# Environment:
#   CONCIERGE_INSTALL_DIR  Override install directory (default: ~/.local/bin)
#
# Supports: Linux x86_64 and aarch64 (musl static binary).
# Other platforms: use  pip install agentic-concierge

set -e

REPO="ausmarton/agentic-concierge"
INSTALL_DIR="${CONCIERGE_INSTALL_DIR:-$HOME/.local/bin}"

# Platform checks
[ "$(uname -s)" = "Linux" ] || {
    echo "[concierge] Linux only; use pip on other platforms:" >&2
    echo "  pip install agentic-concierge" >&2
    exit 1
}

ARCH=$(uname -m)
case "$ARCH" in
    x86_64)        TARGET="x86_64-unknown-linux-musl" ;;
    aarch64|arm64) TARGET="aarch64-unknown-linux-musl" ;;
    *) echo "[concierge] unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

# Resolve latest release tag
LATEST=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/' | grep '^v')
[ -n "$LATEST" ] || {
    echo "[concierge] could not determine latest release" >&2
    exit 1
}

echo "[concierge] installing ${LATEST} for ${TARGET}..."
mkdir -p "$INSTALL_DIR"

TMP=$(mktemp)
curl -fsSL \
    "https://github.com/${REPO}/releases/download/${LATEST}/concierge-${TARGET}" \
    -o "$TMP"
chmod +x "$TMP"
mv "$TMP" "${INSTALL_DIR}/concierge"

echo "[concierge] installed to ${INSTALL_DIR}/concierge"

# PATH hint when install dir is not in PATH
case ":$PATH:" in
    *":${INSTALL_DIR}:"*) ;;
    *) echo "  Add to PATH:  export PATH=\"${INSTALL_DIR}:\$PATH\"" ;;
esac

echo "[concierge] run 'concierge --help' to get started"
