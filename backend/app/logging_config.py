"""Structured logging configuration for Dealer Intel SaaS."""
import logging
import json
import sys
from datetime import datetime, timezone
from typing import Optional


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured log aggregation in production."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "scan_job_id"):
            log_entry["scan_job_id"] = record.scan_job_id
        if hasattr(record, "distributor_id"):
            log_entry["distributor_id"] = record.distributor_id
        if hasattr(record, "channel"):
            log_entry["channel"] = record.channel
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


class DevFormatter(logging.Formatter):
    """Readable formatter for local development."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        prefix = f"{color}[{record.levelname[0]}]{self.RESET}" if color else f"[{record.levelname[0]}]"
        name = record.name.replace("dealer_intel.", "")

        extra_parts = []
        if hasattr(record, "scan_job_id"):
            extra_parts.append(f"job={record.scan_job_id}")
        if hasattr(record, "channel"):
            extra_parts.append(f"ch={record.channel}")
        extra = f" ({', '.join(extra_parts)})" if extra_parts else ""

        return f"{prefix} [{name}]{extra} {record.getMessage()}"


def setup_logging(debug: bool = False) -> None:
    """Configure root and app loggers."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # Remove any existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG if debug else logging.INFO)

    if debug:
        handler.setFormatter(DevFormatter())
    else:
        handler.setFormatter(JSONFormatter())

    root.addHandler(handler)

    # Quiet noisy third-party loggers
    for name in ("httpx", "httpcore", "urllib3", "asyncio", "watchfiles",
                  "hpack", "h2", "h11"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str, scan_job_id: Optional[str] = None) -> logging.Logger:
    """Get a logger with the dealer_intel namespace."""
    logger = logging.getLogger(f"dealer_intel.{name}")
    return logger
