"""Regression test for the 2026-04-21 / 2026-05-11 matcher model decision.

This test exists for one purpose: force any maintainer who wants to bump
``CLAUDE_MODEL`` or ``ENSEMBLE_MODEL`` in ``ai_service.py`` to read the
load-bearing comment by that constant, run the eval, and update this
test deliberately rather than as a silent edit.

History (see ``log.md`` and the comment block above ``CLAUDE_MODEL``):

    2026-04-16  4-6 → 4-7 (scaling-plan upgrade).
    2026-04-21  4-7 → 4-6 (revert; eval showed 4-7 worse on this account's
                image-matching workload).
    2026-05-08  4-6 → 4-7 (Phase-8 author misread the 4-6 constant as
                stale and re-applied the April-16 plan; the April-21
                eval evidence was missed).
    2026-05-11  4-7 → 4-6 (rolled back after a 45-dealer scan + a single-
                dealer probe both produced 0 matches against a campaign
                whose assets had matched cleanly under 4-6 four days
                earlier — same assets, same prompts, only the model
                changed).

If a future bump is intentional:

    1. Run ``backend/eval/`` against the new model.
    2. Confirm the report meets gate.
    3. Update both ``ai_service.CLAUDE_MODEL`` / ``ENSEMBLE_MODEL`` AND
       this test's ``EXPECTED_MATCHER_MODEL`` constant in the same diff.
    4. Add a new entry to the history block in ``ai_service.py`` and
       another row to the table above so the next person can see why.

If you are reading this because the test is failing:

    * Did you mean to bump the matcher model?
    * If yes — go through the four steps above.
    * If no — your change is silently swapping the matcher model and is
      almost certainly going to ship 0 matches in production. Revert.
"""

from app.services import ai_service


# Pinned by deliberate decision on 2026-05-11. See module docstring and
# the comment block above ``ai_service.CLAUDE_MODEL`` before changing.
EXPECTED_MATCHER_MODEL: str = "claude-opus-4-6"


def test_claude_model_pinned_to_eval_winner() -> None:
    """``ai_service.CLAUDE_MODEL`` must equal the eval-validated slug."""
    assert ai_service.CLAUDE_MODEL == EXPECTED_MATCHER_MODEL, (
        f"CLAUDE_MODEL was changed to {ai_service.CLAUDE_MODEL!r} without "
        f"updating this test. Read the comment block above CLAUDE_MODEL in "
        f"backend/app/services/ai_service.py before bumping."
    )


def test_ensemble_model_pinned_to_eval_winner() -> None:
    """``ai_service.ENSEMBLE_MODEL`` must equal the eval-validated slug."""
    assert ai_service.ENSEMBLE_MODEL == EXPECTED_MATCHER_MODEL, (
        f"ENSEMBLE_MODEL was changed to {ai_service.ENSEMBLE_MODEL!r} without "
        f"updating this test. Read the comment block above CLAUDE_MODEL in "
        f"backend/app/services/ai_service.py before bumping."
    )


def test_pinned_model_is_not_in_temperature_denylist() -> None:
    """The pinned model must accept ``temperature=0``.

    The matcher's adaptive thresholds were calibrated assuming
    deterministic scoring. If the pinned model ever ends up in the
    temperature denylist (``_MODELS_THAT_REJECT_TEMPERATURE``), Stage-4
    Opus calls will silently start running at default temperature and
    borderline matches will be killed by run-to-run variance — exactly
    the failure mode that triggered the 2026-05-11 rollback.
    """
    assert not ai_service._model_rejects_temperature(EXPECTED_MATCHER_MODEL), (
        f"{EXPECTED_MATCHER_MODEL!r} ended up in "
        f"_MODELS_THAT_REJECT_TEMPERATURE. The matcher's thresholds assume "
        f"temperature=0; either remove the slug from the denylist or pick "
        f"a different pinned model and update this test."
    )
