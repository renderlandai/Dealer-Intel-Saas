"""Phase 4.6 + Phase 5-minimal guard — worker import path must stay clean.

Two architectural invariants enforced here:

1. **Phase 4.5 (original):** ``app.services.scan_runners`` and everything
   it imports transitively must NOT pull in fastapi, slowapi, or anything
   from the API auth / plan-enforcement stack. This is what made it
   structurally possible to extract a worker process at all.

2. **Phase 5-minimal:** ``app.worker`` itself (the new entry point used by
   the DigitalOcean ``scan-worker`` component) must also stay clean. If a
   future change reaches into a router or a FastAPI middleware to pull in
   request-scoped state, the worker would start dragging in HTTP layer
   modules at boot — wasting RAM and re-coupling the two processes.

Both invariants are tested by the same mechanism: spawn a fresh subprocess
that installs a ``MetaPathFinder`` raising ``ImportError`` for any forbidden
module prefix, then import the target. If the import succeeds with the
guard in place the architecture is intact.

If either of these tests fails, do NOT paper over it. The failure points
straight at the new import that broke the invariant — either move it into
a router-only module or refactor it out of the worker path.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


# Modules that the worker import path must never pull in.
# Add to this list if you decide a new prefix is also API-only.
FORBIDDEN_PREFIXES = ("fastapi", "slowapi")


def _run_isolation_subprocess(import_block: str) -> subprocess.CompletedProcess:
    """Helper: run `import_block` in a fresh subprocess with the guard installed.

    Centralises the boilerplate so each invariant test only writes the
    actual `import` statements it cares about.

    Note on script construction: every line is at column 0. Earlier
    versions used `textwrap.dedent` around an f-string with an
    interpolated multi-line `import_block`, which broke because the
    second-and-later lines of the interpolated block had no leading
    whitespace and confused the dedent's "common prefix" detection. A
    plain string concatenation is unambiguous.
    """
    backend_root = Path(__file__).resolve().parents[1]
    forbidden_repr = repr(FORBIDDEN_PREFIXES)

    prologue = (
        "import sys\n"
        f"FORBIDDEN = {forbidden_repr}\n"
        "\n"
        "class _BlockFinder:\n"
        "    def find_module(self, name, path=None):\n"
        "        if name.startswith(FORBIDDEN):\n"
        "            raise ImportError(\n"
        "                f\"Worker-import isolation violated: {name} is forbidden \"\n"
        "                \"in the worker import path. See Phase 4.5/4.6 / Phase 5-minimal in log.md.\"\n"
        "            )\n"
        "        return None\n"
        "\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.startswith(FORBIDDEN):\n"
        "            raise ImportError(\n"
        "                f\"Worker-import isolation violated: {name} is forbidden \"\n"
        "                \"in the worker import path. See Phase 4.5/4.6 / Phase 5-minimal in log.md.\"\n"
        "            )\n"
        "        return None\n"
        "\n"
        "sys.meta_path.insert(0, _BlockFinder())\n"
        "\n"
    )

    epilogue = (
        "\n"
        "leaked = [m for m in sys.modules if m.startswith(FORBIDDEN)]\n"
        "assert not leaked, f\"Forbidden modules leaked into sys.modules: {leaked}\"\n"
        "print('OK')\n"
    )

    script = prologue + import_block.strip() + "\n" + epilogue

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_scan_runners_imports_without_fastapi_or_slowapi() -> None:
    """`services.scan_runners` (and everything it transitively imports)
    must not depend on fastapi/slowapi."""
    result = _run_isolation_subprocess(
        textwrap.dedent(
            """
            from app.services.scan_runners import (
                run_website_scan,
                run_google_ads_scan,
                run_facebook_scan,
                run_instagram_scan,
                auto_analyze_scan,
                run_image_analysis,
            )
            """
        ).strip()
    )

    assert result.returncode == 0, (
        "Worker-import isolation guard failed for app.services.scan_runners.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_worker_entrypoint_imports_without_fastapi_or_slowapi() -> None:
    """`app.worker` and `app.tasks.execute_persisted_task` must stay clean.

    These are the symbols actually loaded by `python -m app.worker` in the
    DigitalOcean `scan-worker` component. If either pulls in FastAPI the
    worker process boots ~150 MB heavier than it needs to and is no
    longer architecturally separable from the API.
    """
    result = _run_isolation_subprocess(
        textwrap.dedent(
            """
            # Worker entry points and the dispatch helpers it relies on.
            from app.worker import main, _claim_pending_job, _process_one_job
            from app.tasks import execute_persisted_task, KNOWN_TASK_NAMES
            """
        ).strip()
    )

    assert result.returncode == 0, (
        "Worker-import isolation guard failed for app.worker.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "OK" in result.stdout
