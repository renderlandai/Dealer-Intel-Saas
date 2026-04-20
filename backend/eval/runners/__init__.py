"""Per-stage eval runners.

Each runner exercises exactly one surface of the AI pipeline so that a
quality regression can be isolated to the stage that caused it.

Available runners (string ids used by the CLI):

  - ``haiku_filter`` → ``filter_image``
  - ``opus_detect``  → ``detect_asset_in_screenshot``
  - ``verify``       → ``verify_borderline_match``
  - ``compliance``   → ``analyze_compliance``
"""
from .base import CaseResult, RunnerResult, BaseRunner  # noqa: F401
from .haiku_filter import HaikuFilterRunner  # noqa: F401
from .opus_detect import OpusDetectRunner  # noqa: F401
from .verify import VerifyRunner  # noqa: F401
from .compliance import ComplianceRunner  # noqa: F401


RUNNERS = {
    "haiku_filter": HaikuFilterRunner,
    "opus_detect": OpusDetectRunner,
    "verify": VerifyRunner,
    "compliance": ComplianceRunner,
}
