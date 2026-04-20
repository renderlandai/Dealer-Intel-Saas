# Dealer Intel Eval Harness

A reproducible test bench for the AI compliance pipeline (Haiku filter → Opus
detection → verification → compliance). Every change to a model id, prompt,
or threshold is gated against a frozen fixture set with committed baseline
metrics.

## Why

The Opus 4.7 incident (2026-04-20) shipped a model swap with no objective
quality measurement and broke production within hours. The pre-filter
thresholds are untouched not because they're optimal but because we have no
way to prove a tuning change is an improvement. Every prompt edit today is a
roll of the dice.

This harness fixes that. It:

1. Runs the real production AI functions (`filter_image`,
   `detect_asset_in_screenshot`, `verify_borderline_match`,
   `analyze_compliance`) against a frozen labelled fixture set.
2. Computes per-stage precision/recall/F1, plus cost and latency.
3. Diffs the result against `eval/baseline.json` (the last known-good run).
4. Fails the gate when any guarded metric regresses past its tolerance.

## Layout

```
backend/eval/
  README.md                  ← you are here
  config.py                  ← paths + regression thresholds
  manifest.py                ← fixture schema + IO
  build_fixtures.py          ← seed manifest from production match_feedback
  metrics.py                 ← precision/recall/cost math
  baseline.py                ← baseline persistence + diff logic
  report.py                  ← Markdown reporter
  run.py                     ← `python -m eval.run`
  baseline.json              ← committed last-known-good metrics
  runners/
    base.py                  ← shared timing + cost capture
    haiku_filter.py          ← exercises filter_image
    opus_detect.py           ← exercises detect_asset_in_screenshot
    verify.py                ← exercises verify_borderline_match
    compliance.py            ← exercises analyze_compliance
  fixtures/
    manifest.example.json    ← committed template (8 example cases)
    manifest.json            ← gitignored — your real labelled set
    images/                  ← gitignored — image bytes on disk
  reports/                   ← gitignored — per-run Markdown outputs
```

## Quick start

```bash
cd backend
source venv/bin/activate

# 1. Seed fixtures from production data (needs Supabase service role key).
python -m eval.build_fixtures --limit 50

# 2. REVIEW + LABEL the generated manifest.
#    Auto-import only sets a coarse default category — you must hand-correct
#    cases into the right category and tighten the `expected` field.
$EDITOR eval/fixtures/manifest.json

# 3. First-ever run: capture the baseline.
python -m eval.run --update-baseline

# 4. Subsequent runs: gate any prompt / model / threshold change.
python -m eval.run

# 5. To intentionally accept a change (after reviewing the diff):
python -m eval.run --update-baseline
git add eval/baseline.json
```

## Usage

```bash
# Full eval (all four runners), single-threaded.
python -m eval.run

# Single stage — useful while iterating on one prompt.
python -m eval.run --stage haiku_filter
python -m eval.run --stage opus_detect,verify

# Higher concurrency for faster runs (uses more API quota in parallel).
python -m eval.run --concurrency 4

# Dry-run a fixture pull without downloading images.
python -m eval.build_fixtures --dry-run --limit 10
```

Exit codes:
- `0` → gate passed (or first-ever baseline captured)
- `2` → gate failed (regression detected — see report)
- `3` → infrastructure error (no manifest, missing fixtures, env missing)

## Categories

Every fixture is tagged with one of ten categories. Each category exists to
answer a specific quality question:

| Category | Meaning | Tests |
|---|---|---|
| `clear_positive` | Identical creative — recall floor | filter, detect, compliance |
| `template_positive` | Same artwork, dealer name swapped into placeholder | filter, detect |
| `modified_positive` | Cropped / watermarked / colour-shifted match | filter, detect |
| `same_promo_diff_creative` | Same offer/promo code but DIFFERENT artwork | detect must reject |
| `same_brand_diff_campaign` | Same brand but unrelated creative | detect must reject |
| `different_brand` | Completely different brand | filter + detect must reject |
| `borderline_true` | True match scoring 60-80 | verifier must promote |
| `borderline_false` | False match scoring 60-80 | verifier must reject |
| `compliance_drift` | Matched creative + missing required element | compliance must flag |
| `zombie_ad` | Expired campaign still displayed | compliance + zombie check |

## Manifest schema

See `manifest.py` for the dataclasses; `fixtures/manifest.example.json` for a
working sample. Every case is `(id, category, asset_path, discovered_path,
expected)`. The `expected` block declares the ground-truth verdict for the
stages this case exercises.

## Regression thresholds

Defaults live in `config.py` and can be overridden via env vars:

| Threshold | Default | Env var | Why |
|---|---|---|---|
| Recall drop | 2 pts | `EVAL_MAX_RECALL_DROP` | Missed match = customer doesn't catch real violation |
| Precision drop | 5 pts | `EVAL_MAX_PRECISION_DROP` | False match = annoyance, manual review |
| Compliance recall drop | 0 pts | `EVAL_MAX_COMPLIANCE_RECALL_DROP` | Zero tolerance — drift is the product |
| Cost increase | 15% | `EVAL_MAX_COST_INCREASE` | Catches new tokenizer / longer prompts |
| p95 latency increase | 20% | `EVAL_MAX_LATENCY_INCREASE` | Catches slowdowns |
| Score drift (per case) | 10 pts | `EVAL_MAX_SCORE_DRIFT` | Catches subtle prompt changes |
| Score drift (case count) | 5 cases | `EVAL_MAX_SCORE_DRIFT_COUNT` | How many cases may drift before failing |

The compliance-recall threshold is intentionally zero — that's the metric the
customer is paying for; we never accept a regression there without an
explicit `--update-baseline`.

## Workflow for prompt / model changes

1. Make the prompt or model change on a branch.
2. Run `python -m eval.run`.
3. Read the report at `backend/eval/reports/eval-*.md`.
4. If the gate fails:
   - Look at the **Verdict Flips** and **Score Drift** sections — those tell
     you which cases changed behaviour.
   - Look at the **Metric Diffs** table — that tells you which aggregate
     numbers regressed.
   - Either fix the regression or, if it's an intentional improvement that
     happens to flip a few baseline labels, run with `--update-baseline` and
     commit the new `baseline.json` alongside the change.
5. Submit the PR with a link to the report.

## How fixtures are loaded into the runner

The runners mock the network — `download_image` is patched per-call so the
real production AI functions get the fixture bytes from disk instead of
hitting URLs. Everything else (image optimisation, prompt construction,
Anthropic call, cost tracking) is the unmodified production code path.

This means:

- A pricing or model-id change is detected automatically (because the real
  cost tracker runs).
- A prompt change is detected because the real prompts are used.
- A retry / error-handling change is detected.
- A cache-control change is detected — `cache_creation_tokens` and
  `cache_read_tokens` are captured per case.

## Limits / known gaps

- **Hash + CLIP pre-filters are NOT exercised** — those stages are
  byte-deterministic and have their own existing test surface. Add a runner
  later if you start tuning the thresholds.
- **No screenshot pipeline** — fixtures are still images, not full website
  screenshots. The detection runner uses `detect_asset_in_screenshot` which
  handles both, but tile-detection nuance isn't fully tested.
- **Auto-import categories are coarse** — `build_fixtures.py` maps every
  `false_positive` to `borderline_false`. You must hand-correct.
- **Concurrency caveat** — running with `--concurrency > 1` may produce
  slightly different cache behaviour because the Anthropic 5-minute
  ephemeral cache is process-global. For diff-stable results, keep
  `--concurrency 1` when capturing a baseline.

## Cost guardrail

A full eval run on 50 fixtures × 4 runners ≈ ~$1.50-3.00 on Claude. Budget
accordingly when wiring this into CI — running on every PR is fine, running
on every commit is wasteful.
