"""Unit tests for `scan_runners._normalize_scan_error`.

The normaliser is the single source of truth for the `error_message`
column on `scan_jobs`. We want it to:

* Translate Playwright "browser binary missing" failures into a stable,
  actionable message that the frontend heuristic can also recognise.
* Leave every other exception untouched (so we don't accidentally hide
  meaningful errors from operators).
* Preserve the original message text inside the normalised output so
  Sentry / log greps still find it.
* Never raise — even on weird inputs like exceptions with no string repr.

These tests run cheaply because the function has no external deps.
"""
from __future__ import annotations

import pytest

from app.services.scan_runners import _normalize_scan_error


# ---------------------------------------------------------------------------
# Playwright "executable doesn't exist" — the original real-world failure.
# ---------------------------------------------------------------------------

PLAYWRIGHT_RAW = (
    "BrowserType.launch: Executable doesn't exist at "
    "/var/folders/wm/abc/T/cursor-sandbox-cache/123/ms-playwright/"
    "chromium_headless_shell-1193/chrome-mac/headless_shell\n"
    "╔══════════════════════════════════════════════════════╗\n"
    "║ Looks like Playwright was just installed or updated. ║\n"
    "║ Please run the following command to download new     ║\n"
    "║ browsers:                                            ║\n"
    "║                                                      ║\n"
    "║     playwright install                               ║\n"
    "╚══════════════════════════════════════════════════════╝"
)


class TestPlaywrightDetection:
    """All known shapes of the Playwright browser-missing error map to the
    same normalised, actionable message."""

    def test_full_real_world_traceback_is_normalised(self):
        out = _normalize_scan_error(RuntimeError(PLAYWRIGHT_RAW))
        assert out.startswith("Browser runtime not installed:")
        assert "install_playwright.sh" in out
        assert "playwright install chromium" in out

    def test_only_executable_doesnt_exist_substring_triggers(self):
        msg = "BrowserType.launch: Executable doesn't exist at /tmp/foo"
        out = _normalize_scan_error(Exception(msg))
        assert out.startswith("Browser runtime not installed:")

    def test_only_install_hint_substring_triggers(self):
        msg = "something blew up. Please run: playwright install"
        out = _normalize_scan_error(Exception(msg))
        assert out.startswith("Browser runtime not installed:")

    def test_only_chrome_headless_shell_substring_triggers(self):
        msg = "ENOENT: no such file or directory, open '/x/chrome-headless-shell'"
        out = _normalize_scan_error(Exception(msg))
        assert out.startswith("Browser runtime not installed:")

    def test_detection_is_case_insensitive(self):
        msg = "BROWSERTYPE.LAUNCH: EXECUTABLE DOESN'T EXIST at ..."
        out = _normalize_scan_error(Exception(msg))
        assert out.startswith("Browser runtime not installed:")

    def test_original_message_is_preserved_in_output(self):
        out = _normalize_scan_error(RuntimeError(PLAYWRIGHT_RAW))
        # Newlines collapsed but the distinctive substring still appears.
        assert "BrowserType.launch" in out

    def test_long_original_is_truncated_to_240_chars(self):
        very_long = "BrowserType.launch: Executable doesn't exist at " + ("X" * 5_000)
        out = _normalize_scan_error(Exception(very_long))
        # The truncated original snippet lives after "Original: ".
        snippet = out.split("Original: ", 1)[1]
        assert len(snippet) <= 240

    def test_actionable_hint_mentions_both_local_and_prod_paths(self):
        out = _normalize_scan_error(RuntimeError(PLAYWRIGHT_RAW))
        # Local-dev path
        assert "install_playwright.sh" in out
        # Production path
        assert "redeploy" in out.lower()
        assert "docker" in out.lower()


# ---------------------------------------------------------------------------
# Non-matching exceptions must pass through unchanged.
# ---------------------------------------------------------------------------

class TestNonPlaywrightPassthrough:
    """Anything that isn't a Playwright browser-missing failure should be
    returned verbatim so we don't hide meaningful errors."""

    def test_generic_runtime_error_is_unchanged(self):
        msg = "Something completely unrelated went wrong"
        assert _normalize_scan_error(RuntimeError(msg)) == msg

    def test_timeout_error_is_unchanged(self):
        msg = "asyncio.exceptions.TimeoutError"
        assert _normalize_scan_error(TimeoutError(msg)) == msg

    def test_http_404_error_is_unchanged(self):
        msg = "HTTP 404: Not Found from https://example.com/ad/123"
        assert _normalize_scan_error(Exception(msg)) == msg

    def test_serpapi_rate_limit_is_unchanged(self):
        msg = "SerpApi rate limit exceeded — retry in 60s"
        assert _normalize_scan_error(Exception(msg)) == msg

    def test_unrelated_playwright_navigation_error_is_unchanged(self):
        # A real Playwright nav error that isn't about missing binaries.
        msg = "Page.goto: Timeout 30000ms exceeded."
        assert _normalize_scan_error(Exception(msg)) == msg


# ---------------------------------------------------------------------------
# Robustness: weird / edge-case inputs.
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_message_falls_back_to_class_name(self):
        out = _normalize_scan_error(ValueError(""))
        assert out == "ValueError"

    def test_exception_without_str_returns_class_name(self):
        out = _normalize_scan_error(KeyError())
        # KeyError() with no args stringifies to "" so we expect class name.
        assert out == "KeyError"

    def test_normalizer_never_raises(self):
        class WeirdExc(Exception):
            def __str__(self) -> str:  # noqa: D401
                return "BrowserType.launch: Executable doesn't exist"
        # Should still detect and normalise even with a custom __str__.
        out = _normalize_scan_error(WeirdExc())
        assert out.startswith("Browser runtime not installed:")
