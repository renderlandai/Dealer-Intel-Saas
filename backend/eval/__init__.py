"""Dealer Intel evaluation harness.

A reproducible, deterministic test bench for the AI compliance pipeline
(Haiku filter → Opus detection → verification → compliance).  Every change
to a model id, prompt, or threshold is gated against a frozen fixture set
with committed baseline metrics.

See ``backend/eval/README.md`` for usage.
"""
