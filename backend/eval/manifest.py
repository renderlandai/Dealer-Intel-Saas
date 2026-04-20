"""Fixture manifest schema and IO.

A manifest is a JSON document listing every labelled `(asset, discovered)`
pair the harness will exercise.  Image bytes live on disk under
``fixtures/images/`` so the eval is reproducible regardless of whether the
original source URLs are still alive.

Schema (one object per case)::

    {
      "id": "match-2026-04-19-001",                  # stable, human-friendly
      "category": "clear_positive",                   # see CATEGORIES below
      "asset_path":      "images/asset_001.jpg",     # relative to fixtures dir
      "discovered_path": "images/discovered_001.jpg",

      # Ground-truth labels — at least one must be set per category.
      "expected": {
        "is_relevant":   true,            # Haiku filter expectation
        "is_match":      true,            # Opus detection expectation
        "min_score":     70,              # detection confidence floor
        "max_score":     100,             # detection confidence ceiling
        "is_compliant":  false,           # compliance verdict (only for compliance cases)
        "zombie_ad":     false
      },

      # Optional context to make labels reviewable later.
      "notes":           "Same campaign, dealer name swapped",
      "source": {
        "scan_job_id":   "<uuid>",        # provenance from production data
        "match_id":      "<uuid>",
        "labelled_by":   "ops@example.com",
        "labelled_at":   "2026-04-20T14:21:00Z"
      },

      # Optional brand-rules payload for compliance fixtures.
      "brand_rules": {
        "required_elements":  ["Manufacturer logo", "APR disclaimer"],
        "forbidden_elements": ["Competitor branding"],
        "brand_colors":       ["#003366"]
      },
      "campaign_end_date": "2026-03-31"
    }

The full manifest is::

    {
      "version": 1,
      "generated_at": "...",
      "cases": [ {...}, {...}, ... ]
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# Canonical category list.  Each category answers a distinct quality
# question; see backend/eval/README.md for the full rubric.
CATEGORIES: List[str] = [
    "clear_positive",          # obvious match, recall floor
    "template_positive",       # dealer-name placeholder swap
    "modified_positive",       # cropped / watermarked / colour-shifted
    "same_promo_diff_creative",  # highest false-positive risk
    "same_brand_diff_campaign",  # tests brand-confusion rejection
    "different_brand",         # precision floor
    "borderline_true",         # true match scoring 60–80
    "borderline_false",        # false match scoring 60–80
    "compliance_drift",        # matched + brand violation
    "zombie_ad",               # expired campaign still live
]


@dataclass
class Expected:
    is_relevant: Optional[bool] = None
    is_match: Optional[bool] = None
    min_score: Optional[int] = None
    max_score: Optional[int] = None
    is_compliant: Optional[bool] = None
    zombie_ad: Optional[bool] = None

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class FixtureCase:
    id: str
    category: str
    asset_path: str
    discovered_path: str
    expected: Expected
    notes: str = ""
    source: Dict[str, Any] = field(default_factory=dict)
    brand_rules: Dict[str, Any] = field(default_factory=dict)
    campaign_end_date: Optional[str] = None

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(
                f"Unknown fixture category {self.category!r} for {self.id} — "
                f"must be one of: {', '.join(CATEGORIES)}"
            )

    def asset_bytes(self, fixtures_dir: Path) -> bytes:
        return (fixtures_dir / self.asset_path).read_bytes()

    def discovered_bytes(self, fixtures_dir: Path) -> bytes:
        return (fixtures_dir / self.discovered_path).read_bytes()

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "id": self.id,
            "category": self.category,
            "asset_path": self.asset_path,
            "discovered_path": self.discovered_path,
            "expected": self.expected.as_dict(),
        }
        if self.notes:
            out["notes"] = self.notes
        if self.source:
            out["source"] = self.source
        if self.brand_rules:
            out["brand_rules"] = self.brand_rules
        if self.campaign_end_date:
            out["campaign_end_date"] = self.campaign_end_date
        return out


@dataclass
class Manifest:
    version: int = 1
    generated_at: str = ""
    cases: List[FixtureCase] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        if not path.exists():
            raise FileNotFoundError(
                f"Fixture manifest not found at {path}. "
                f"Seed it via 'python -m eval.build_fixtures' or "
                f"copy 'manifest.example.json' to 'manifest.json' and edit."
            )
        raw = json.loads(path.read_text())
        cases = [
            FixtureCase(
                id=c["id"],
                category=c["category"],
                asset_path=c["asset_path"],
                discovered_path=c["discovered_path"],
                expected=Expected(**c.get("expected", {})),
                notes=c.get("notes", ""),
                source=c.get("source", {}),
                brand_rules=c.get("brand_rules", {}),
                campaign_end_date=c.get("campaign_end_date"),
            )
            for c in raw.get("cases", [])
        ]
        return cls(
            version=raw.get("version", 1),
            generated_at=raw.get("generated_at", ""),
            cases=cases,
        )

    def save(self, path: Path) -> None:
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = {
            "version": self.version,
            "generated_at": self.generated_at,
            "cases": [c.as_dict() for c in self.cases],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")

    def by_category(self) -> Dict[str, List[FixtureCase]]:
        groups: Dict[str, List[FixtureCase]] = {c: [] for c in CATEGORIES}
        for case in self.cases:
            groups[case.category].append(case)
        return groups

    def summary(self) -> str:
        groups = self.by_category()
        lines = [f"Manifest v{self.version} generated {self.generated_at}"]
        lines.append(f"  Total cases: {len(self.cases)}")
        for cat in CATEGORIES:
            count = len(groups[cat])
            if count:
                lines.append(f"    {cat:<28} {count}")
        return "\n".join(lines)
