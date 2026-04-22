"""Phase 4.6 guard — `services/scan_runners` must stay worker-safe.

This test enforces the architectural invariant established in Phase 4.5:
the scan-pipeline coroutines (and everything they import transitively)
must NOT pull in fastapi, slowapi, or anything from the API auth /
plan-enforcement stack. Re-coupling would silently undo the work that
makes a separate worker process possible.

How it works:
    1. Spawn a fresh subprocess so we don't see modules already imported
       by other tests (pytest itself imports fastapi indirectly).
    2. In the subprocess, install a `MetaPathFinder` that raises
       `ImportError` the moment anything tries to load a forbidden
       package.
    3. Then `import` every public scan-runner symbol.
    4. If the import succeeds with the guard in place, the architecture
       is intact.

If this test ever fails, it means a new dependency was added somewhere
in the `services/scan_runners` import closure that pulls FastAPI back
in. Don't paper over the failure — find the offending import and either
move it into a router-only module or refactor it out of the runner path.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


# Modules that the worker import path must never pull in.
# Add to this list if you decide a new prefix is also API-only.
FORBIDDEN_PREFIXES = ("fastapi", "slowapi")


def test_scan_runners_imports_without_fastapi_or_slowapi() -> None:
    """`services.scan_runners` (and everything it transitively imports)
    must not depend on fastapi/slowapi."""
    backend_root = Path(__file__).resolve().parents[1]
    forbidden_repr = repr(FORBIDDEN_PREFIXES)

    script = textwrap.dedent(
        f"""
        import sys

        FORBIDDEN = {forbidden_repr}

        class _BlockFinder:
            def find_module(self, name, path=None):
                if name.startswith(FORBIDDEN):
                    raise ImportError(
                        f"Worker-import isolation violated: {{name}} is forbidden "
                        "in app.services.scan_runners. See Phase 4.5/4.6 in log.md."
                    )
                return None

            # Python 3.4+ also calls find_spec; raise the same way.
            def find_spec(self, name, path=None, target=None):
                if name.startswith(FORBIDDEN):
                    raise ImportError(
                        f"Worker-import isolation violated: {{name}} is forbidden "
                        "in app.services.scan_runners. See Phase 4.5/4.6 in log.md."
                    )
                return None

        sys.meta_path.insert(0, _BlockFinder())

        # Importing this module is the entire point of the test.
        from app.services.scan_runners import (
            run_website_scan,
            run_google_ads_scan,
            run_facebook_scan,
            run_instagram_scan,
            auto_analyze_scan,
            run_image_analysis,
        )

        # Sanity-check: confirm none of the forbidden modules slipped in.
        leaked = [m for m in sys.modules if m.startswith(FORBIDDEN)]
        assert not leaked, f"Forbidden modules leaked into sys.modules: {{leaked}}"
        print("OK")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        "Worker-import isolation guard failed.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "OK" in result.stdout
