#!/usr/bin/env sh
# install.sh — one-liner installer for the agentic-concierge launcher binary.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ausmarton/agentic-concierge/main/install.sh | sh
#
# Environment:
#   CONCIERGE_INSTALL_DIR  Override install directory (default: ~/.local/bin)
#
# Supports: Linux x86_64/aarch64 (musl static binary), macOS x86_64/arm64.
# Other platforms: use  pip install agentic-concierge

set -e

REPO="ausmarton/agentic-concierge"
INSTALL_DIR="${CONCIERGE_INSTALL_DIR:-$HOME/.local/bin}"

# Platform + architecture detection
ARCH=$(uname -m)
OS=$(uname -s)
case "$OS" in
  Linux)
    case "$ARCH" in
      x86_64)        TARGET="x86_64-unknown-linux-musl" ;;
      aarch64|arm64) TARGET="aarch64-unknown-linux-musl" ;;
      *) echo "[concierge] unsupported arch: $ARCH" >&2; exit 1 ;;
    esac ;;
  Darwin)
    case "$ARCH" in
      x86_64) TARGET="x86_64-apple-darwin" ;;
      arm64)  TARGET="aarch64-apple-darwin" ;;
      *) echo "[concierge] unsupported arch: $ARCH" >&2; exit 1 ;;
    esac ;;
  *)
    echo "[concierge] unsupported OS: $OS — use: pip install agentic-concierge" >&2
    exit 1 ;;
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

BINARY_URL="https://github.com/${REPO}/releases/download/${LATEST}/concierge-${TARGET}"
TMP=$(mktemp)

# Attempt binary download; fall back to pip if the asset is not yet on the release.
if curl -fsSL "$BINARY_URL" -o "$TMP" 2>/dev/null; then
    chmod +x "$TMP"
    mv "$TMP" "${INSTALL_DIR}/concierge"
    echo "[concierge] installed to ${INSTALL_DIR}/concierge"
else
    rm -f "$TMP"
    echo "[concierge] native binary not yet available for ${TARGET} in ${LATEST}." >&2
    echo "[concierge] falling back to: pip install agentic-concierge" >&2
    if command -v pip3 >/dev/null 2>&1; then
        pip3 install --quiet "agentic-concierge==${LATEST#v}"
        echo "[concierge] installed via pip (use 'concierge' from your Python environment)"
    elif command -v pip >/dev/null 2>&1; then
        pip install --quiet "agentic-concierge==${LATEST#v}"
        echo "[concierge] installed via pip (use 'concierge' from your Python environment)"
    else
        echo "[concierge] pip not found. Install manually:" >&2
        echo "    pip install agentic-concierge" >&2
        exit 1
    fi
    exit 0
fi

# PATH hint when install dir is not in PATH
case ":$PATH:" in
    *":${INSTALL_DIR}:"*) ;;
    *) echo "  Add to PATH:  export PATH=\"${INSTALL_DIR}:\$PATH\"" ;;
esac

echo "[concierge] run 'concierge --help' to get started"
