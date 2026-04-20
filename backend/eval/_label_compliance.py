"""One-shot helper to hand-label compliance fixtures in manifest.json.

Run from backend/: ``venv/bin/python -m eval._label_compliance``

Idempotent: re-applies the labels even if the script is run twice.
The chosen cases were eyeballed against the real fixture images on
2026-04-20 and represent a mix of:
  - compliant Yancey CAT promos with brand-rule + end-date metadata
  - missing-required-element compliance violations
  - one zombie ad (campaign_end_date in the past)
"""
from __future__ import annotations

import json
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent / "fixtures" / "manifest.json"


# Labels: case_id_prefix → patch dict
LABELS = {
    "feedback-7cd06bf2-b5d2-4a06-9590-cad58a70d914": {
        # 25% Off Advansys Teeth promo, Yancey CAT logo + promo code +
        # "OFFER VALID THROUGH 6/30/2026" disclaimer all visible.
        "category": "clear_positive",
        "expected_patch": {"is_compliant": True, "zombie_ad": False},
        "brand_rules": {
            "required_elements": [
                "Yancey CAT logo",
                "Promo code",
                "Offer expiration date",
            ],
            "forbidden_elements": ["Competitor branding"],
            "brand_colors": ["#FFCC00", "#000000"],
        },
        "campaign_end_date": "2026-06-30",
        "notes": (
            "Hand-labelled 2026-04-20: 25% Off Advansys Teeth — fully "
            "compliant Yancey CAT promo with logo, promo code, and "
            "expiration disclaimer."
        ),
    },
    "feedback-9c57ed94-0cf9-4608-a6a5-f1f0712b18e8": {
        # 10% Off Engine Components, Yancey CAT logo + "OFFER VALID
        # THROUGH 6/30/2026" + "PCC ONLY" small print.
        "category": "clear_positive",
        "expected_patch": {"is_compliant": True, "zombie_ad": False},
        "brand_rules": {
            "required_elements": [
                "Yancey CAT logo",
                "Offer expiration date",
            ],
            "forbidden_elements": ["Competitor branding"],
            "brand_colors": ["#FFCC00", "#000000"],
        },
        "campaign_end_date": "2026-06-30",
        "notes": (
            "Hand-labelled 2026-04-20: 10% Off Engine Component Parts — "
            "compliant promo with Yancey CAT logo + valid-through date."
        ),
    },
    "feedback-1095ee74-87a3-4d43-a997-6653f4b4a26a": {
        # CAT 307.5 Mini Excavator product hero (evergreen, not a promo).
        "category": "clear_positive",
        "expected_patch": {"is_compliant": True, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["CAT branding"],
            "forbidden_elements": ["Competitor branding"],
        },
        # Evergreen product page — intentionally no campaign_end_date.
        "notes": (
            "Hand-labelled 2026-04-20: CAT 307.5 Mini Excavator product "
            "hero — evergreen marketing, not date-bound."
        ),
    },
    "feedback-c8c0c0f4-0ba8-4549-997a-4418b7420b93": {
        # 20% Off Labor Charge for BCP/CCE — NO Yancey CAT logo, NO
        # expiration disclaimer.  Required elements absent → drift.
        "category": "compliance_drift",
        "expected_patch": {"is_compliant": False, "zombie_ad": False},
        "brand_rules": {
            "required_elements": [
                "Yancey CAT logo",
                "Offer expiration date",
            ],
            "forbidden_elements": ["Competitor branding"],
            "brand_colors": ["#FFCC00", "#000000"],
        },
        "campaign_end_date": "2026-12-31",
        "notes": (
            "Hand-labelled 2026-04-20: 20% Off Labor — missing Yancey "
            "CAT logo and expiration disclaimer.  Drift expected."
        ),
    },
    "feedback-2741b80a-cc88-4693-a461-ade66a2687af": {
        # "Next-Day Parts / Two-Day Repairs" with CVA badge but NO
        # Yancey CAT logo — required element missing.
        "category": "compliance_drift",
        "expected_patch": {"is_compliant": False, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["Yancey CAT logo"],
            "forbidden_elements": ["Competitor branding"],
        },
        "campaign_end_date": "2026-12-31",
        "notes": (
            "Hand-labelled 2026-04-20: Next-Day Parts / Two-Day Repairs "
            "creative — only CVA badge, no Yancey CAT logo."
        ),
    },
    "feedback-91713971-9846-479c-8441-3fc773f16448": {
        # Retail Special — Used Small Tools.  No on-image expiration,
        # so we metadata-flag it as past-end-date to test zombie logic.
        "category": "zombie_ad",
        "expected_patch": {"is_compliant": False, "zombie_ad": True},
        "brand_rules": {},
        "campaign_end_date": "2026-01-15",
        "notes": (
            "Hand-labelled 2026-04-20: Retail Special creative re-purposed "
            "as a zombie test — campaign_end_date set in the past."
        ),
    },

    # --- Round 2 (2026-04-20) — labelling the remaining clusters --------
    # Cluster 1: CAT 307.5 Mini Excavator hero (B&W).
    "feedback-1fb27b39-614b-4efd-8a6e-f149b52d38f9": {
        "category": "clear_positive",
        "expected_patch": {"is_compliant": True, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["CAT branding"],
            "forbidden_elements": ["Competitor branding"],
        },
        "notes": (
            "Hand-labelled 2026-04-20: CAT 307.5 Mini Excavator hero "
            "(B&W variant of feedback-1095ee74) — evergreen product page."
        ),
    },

    # Cluster 2: 10% Off Undercarriage promo, full Yancey CAT branding +
    # promo code GROUND10 + "VALID THROUGH 6/30/2026" disclaimer.
    "feedback-ff223913-a3b5-4d34-960d-8143d60f3f9b": {
        "category": "clear_positive",
        "expected_patch": {"is_compliant": True, "zombie_ad": False},
        "brand_rules": {
            "required_elements": [
                "Yancey CAT logo",
                "Promo code",
                "Offer expiration date",
            ],
            "forbidden_elements": ["Competitor branding"],
            "brand_colors": ["#FFCC00", "#000000"],
        },
        "campaign_end_date": "2026-06-30",
        "notes": (
            "Hand-labelled 2026-04-20: 10% Off Undercarriage promo "
            "(GROUND10) — fully compliant, has logo + code + date."
        ),
    },

    # Cluster 3 (5 dupes): "FREE UNDERCARRIAGE INSPECTION" B&W creative,
    # missing required Yancey CAT logo.
    "feedback-9b068a88-0247-4841-9082-6599698fa302": {
        "category": "compliance_drift",
        "expected_patch": {"is_compliant": False, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["Yancey CAT logo"],
            "forbidden_elements": ["Competitor branding"],
        },
        "campaign_end_date": "2026-12-31",
        "notes": (
            "Hand-labelled 2026-04-20: Free Undercarriage Inspection "
            "creative — missing Yancey CAT logo."
        ),
    },
    "feedback-ee10889a-cc2c-4dfe-81b2-744c95f9c3d6": {
        "category": "compliance_drift",
        "expected_patch": {"is_compliant": False, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["Yancey CAT logo"],
            "forbidden_elements": ["Competitor branding"],
        },
        "campaign_end_date": "2026-12-31",
        "notes": "Hand-labelled 2026-04-20: dup of feedback-9b068a88 (same image bytes).",
    },
    "feedback-db291585-921b-414a-a796-c4e65ac12d0e": {
        "category": "compliance_drift",
        "expected_patch": {"is_compliant": False, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["Yancey CAT logo"],
            "forbidden_elements": ["Competitor branding"],
        },
        "campaign_end_date": "2026-12-31",
        "notes": "Hand-labelled 2026-04-20: dup of feedback-9b068a88 (same image bytes).",
    },
    "feedback-a0d36c1a-264c-4578-aff2-ed45744d1653": {
        "category": "compliance_drift",
        "expected_patch": {"is_compliant": False, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["Yancey CAT logo"],
            "forbidden_elements": ["Competitor branding"],
        },
        "campaign_end_date": "2026-12-31",
        "notes": "Hand-labelled 2026-04-20: dup of feedback-9b068a88 (same image bytes).",
    },
    "feedback-64a7396a-7273-48fc-ae66-773a4fbda994": {
        "category": "compliance_drift",
        "expected_patch": {"is_compliant": False, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["Yancey CAT logo"],
            "forbidden_elements": ["Competitor branding"],
        },
        "campaign_end_date": "2026-12-31",
        "notes": "Hand-labelled 2026-04-20: dup of feedback-9b068a88 (same image bytes).",
    },

    # Cluster 4 (2 dupes): 10% Off Online Purchases (PCC10) — CAT-
    # corporate Parts.Cat.Com / Cat Central App marketing.  Carries CAT
    # Central logo but NOT a dealer (Yancey) logo, so its compliance
    # rules are different (CAT-only branding requirements).
    "feedback-a5c98008-71ac-4387-8ab4-0c373b94b0a2": {
        "category": "clear_positive",
        "expected_patch": {"is_compliant": True, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["CAT branding", "Promo code"],
            "forbidden_elements": ["Competitor branding"],
            "brand_colors": ["#FFCC00", "#000000"],
        },
        "notes": (
            "Hand-labelled 2026-04-20: 10% Off Online Purchases (PCC10) "
            "— CAT corporate ad with CAT Central logo + promo code."
        ),
    },
    "feedback-bc8a67ba-4bd1-4604-a816-17f2a9f1cfd6": {
        "category": "clear_positive",
        "expected_patch": {"is_compliant": True, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["CAT branding", "Promo code"],
            "forbidden_elements": ["Competitor branding"],
            "brand_colors": ["#FFCC00", "#000000"],
        },
        "notes": "Hand-labelled 2026-04-20: dup of feedback-a5c98008 (same image bytes).",
    },

    # Cluster 5: "Retail Special — Used Small Tools" — same source image
    # as the zombie fixture (feedback-91713971) but graded WITHOUT a past
    # campaign_end_date so we get an isolated read on missing-logo drift.
    "feedback-95c08729-6511-4a6e-8f25-2bdec2b3ca6c": {
        "category": "compliance_drift",
        "expected_patch": {"is_compliant": False, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["Yancey CAT logo"],
            "forbidden_elements": ["Competitor branding"],
        },
        "campaign_end_date": "2026-12-31",
        "notes": (
            "Hand-labelled 2026-04-20: Retail Special creative — control "
            "case for the zombie fixture (same image bytes, no past end "
            "date), tests missing-Yancey-logo detection in isolation."
        ),
    },

    # Cluster 6: "FREE UNDERCARRIAGE INSPECTION" full-colour version.
    "feedback-2e307d3b-0a29-4e14-9426-b8d68147aa12": {
        "category": "compliance_drift",
        "expected_patch": {"is_compliant": False, "zombie_ad": False},
        "brand_rules": {
            "required_elements": ["Yancey CAT logo"],
            "forbidden_elements": ["Competitor branding"],
        },
        "campaign_end_date": "2026-12-31",
        "notes": (
            "Hand-labelled 2026-04-20: Free Undercarriage Inspection "
            "(colour variant of cluster 3) — missing Yancey CAT logo."
        ),
    },
}


def main() -> int:
    raw = json.loads(MANIFEST_PATH.read_text())
    cases = raw.get("cases", [])

    label_keys = set(LABELS.keys())
    matched = 0
    for case in cases:
        cid = case.get("id", "")
        if cid not in label_keys:
            continue
        patch = LABELS[cid]
        case["category"] = patch["category"]
        case.setdefault("expected", {}).update(patch["expected_patch"])
        case["brand_rules"] = patch["brand_rules"]
        if patch.get("campaign_end_date"):
            case["campaign_end_date"] = patch["campaign_end_date"]
        elif "campaign_end_date" in case:
            del case["campaign_end_date"]
        case["notes"] = patch["notes"]
        matched += 1

    if matched != len(LABELS):
        missing = label_keys - {c.get("id", "") for c in cases}
        print(f"WARN: {len(missing)} target case_id(s) missing from manifest:")
        for m in missing:
            print(f"  - {m}")

    MANIFEST_PATH.write_text(json.dumps(raw, indent=2, sort_keys=False) + "\n")
    print(f"Patched {matched}/{len(LABELS)} cases in {MANIFEST_PATH}")

    # Re-summarise category breakdown.
    from collections import Counter
    cats = Counter(c["category"] for c in cases)
    print("Category breakdown after labelling:")
    for cat, n in sorted(cats.items(), key=lambda kv: -kv[1]):
        print(f"  {cat:<28} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
