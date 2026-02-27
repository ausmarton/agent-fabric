#!/usr/bin/env sh
# generate_signing_key.sh — one-time Ed25519 key generation for launcher signing.
#
# Run this ONCE to produce a keypair.  Store the private key as the CI secret
# LAUNCHER_SIGNING_KEY_PEM.  Paste the public key bytes into update.rs.
#
# Requirements: OpenSSL >= 1.1.1 (Ed25519 support)
#
# Usage:
#   sh scripts/generate_signing_key.sh
#
# Output:
#   1. Prints the 32 public-key bytes as a Rust array literal — paste into
#      `SIGNING_PUBLIC_KEY` in `launcher/src/update.rs`.
#   2. Prints the PEM-encoded private key — store as CI secret
#      LAUNCHER_SIGNING_KEY_PEM (used by release.yml signing step).
#
# Security notes:
#   - The private key is only printed to stdout; it is never written to disk.
#   - After pasting the public key into update.rs, discard or securely store
#     the private key PEM string.  If the private key is compromised, rotate:
#     run this script again, update update.rs, and re-build/re-release.

set -e

# Verify openssl supports Ed25519
openssl genpkey -algorithm ed25519 -out /dev/null 2>/dev/null || {
    echo "ERROR: OpenSSL does not support Ed25519.  Upgrade to OpenSSL >= 1.1.1." >&2
    exit 1
}

echo "=== Generating Ed25519 keypair ==="
echo ""

# Generate private key (to stdout only — never written to disk)
PRIVATE_PEM=$(openssl genpkey -algorithm ed25519 2>/dev/null)

# Extract public key as 32 raw bytes (last 32 bytes of DER SubjectPublicKeyInfo)
PUB_BYTES=$(printf '%s\n' "$PRIVATE_PEM" \
    | openssl pkey -pubout -outform DER 2>/dev/null \
    | tail -c 32 \
    | od -An -tu1 \
    | tr -s ' \n' ' ' \
    | sed 's/^ //' \
    | awk '{for(i=1;i<=NF;i++) printf "%d, ", $i; print ""}')

echo "=== PUBLIC KEY (paste into launcher/src/update.rs SIGNING_PUBLIC_KEY) ==="
echo ""
echo "const SIGNING_PUBLIC_KEY: [u8; 32] = ["
echo "    ${PUB_BYTES}"
echo "];"
echo ""

echo "=== PRIVATE KEY (store as CI secret LAUNCHER_SIGNING_KEY_PEM) ==="
echo ""
printf '%s\n' "$PRIVATE_PEM"
echo ""

echo "=== Instructions ==="
echo "1. Copy the SIGNING_PUBLIC_KEY array above into launcher/src/update.rs."
echo "2. Copy the PRIVATE KEY PEM above into your CI/CD secret LAUNCHER_SIGNING_KEY_PEM."
echo "3. Rebuild and release — the release.yml workflow will sign binaries automatically."
echo "4. Do NOT commit the private key to version control."
