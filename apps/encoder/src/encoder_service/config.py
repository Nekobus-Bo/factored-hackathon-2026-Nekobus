"""Configuration management for encoder service."""

import os


def get_abstention_threshold() -> float | None:
    """Retrieve the abstention threshold (tau) from the environment.

    Returns:
        float | None: The calibrated threshold if set, or None if uncalibrated.

    Raises:
        ValueError: If ABSTENTION_THRESHOLD is present but not a valid float in [0, 1].
    """
    raw_val = os.getenv("ABSTENTION_THRESHOLD")
    if raw_val is None or not raw_val.strip():
        return None

    cleaned = raw_val.strip()
    try:
        tau = float(cleaned)
    except ValueError as err:
        raise ValueError(
            f"ABSTENTION_THRESHOLD must be a valid float in [0.0, 1.0], got '{raw_val}'"
        ) from err

    if not (0.0 <= tau <= 1.0):
        raise ValueError(f"ABSTENTION_THRESHOLD must be between 0.0 and 1.0, got {tau}")

    return tau
