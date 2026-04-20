#!/usr/bin/env bash
# Install Playwright Chromium for the website-scan worker.
#
# Why this script exists:
#   When run inside Cursor's sandbox (or any environment where Node's
#   `os.cpus()` returns []), Playwright cannot detect Apple Silicon and
#   downloads mac-x64 binaries. The Python runtime then looks for
#   chrome-headless-shell-mac-arm64/ and fails with:
#
#       BrowserType.launch: Executable doesn't exist at .../chrome-headless-shell
#
#   We force the correct platform via PLAYWRIGHT_HOST_PLATFORM_OVERRIDE so the
#   installer fetches the matching arm64 build on Apple Silicon Macs.
#
# Usage:
#   cd backend && ./scripts/install_playwright.sh
#
# Re-run safely any time; pass --force to wipe and reinstall.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$BACKEND_DIR"

if [[ ! -d venv ]]; then
    echo "error: backend/venv not found. Run 'python3 -m venv venv && pip install -r requirements.txt' first." >&2
    exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate

OS_NAME="$(uname -s)"
ARCH_NAME="$(uname -m)"

OVERRIDE=""
if [[ "$OS_NAME" == "Darwin" && "$ARCH_NAME" == "arm64" ]]; then
    # macOS major version mapping used by Playwright is min(release-9, 15).
    # We pin to mac15-arm64 (latest officially-supported tag) which works for
    # macOS 13+ on Apple Silicon.
    OVERRIDE="mac15-arm64"
fi

FORCE_FLAG=""
if [[ "${1:-}" == "--force" ]]; then
    FORCE_FLAG="--force"
fi

echo "Installing Playwright Chromium (host=${OS_NAME}/${ARCH_NAME}, override=${OVERRIDE:-auto})"

if [[ -n "$OVERRIDE" ]]; then
    PLAYWRIGHT_HOST_PLATFORM_OVERRIDE="$OVERRIDE" python -m playwright install $FORCE_FLAG chromium
else
    python -m playwright install $FORCE_FLAG chromium
fi

echo "Playwright Chromium ready."
