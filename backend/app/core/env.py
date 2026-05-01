import logging
import os

logger = logging.getLogger(__name__)


def get_int_env(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "invalid integer env %s=%r, using default %s",
            name,
            raw,
            default,
        )
        return default
    if minimum is not None and value < minimum:
        logger.warning(
            "env %s=%r is below minimum %s, using default %s",
            name,
            raw,
            minimum,
            default,
        )
        return default
    if maximum is not None and value > maximum:
        logger.warning(
            "env %s=%r is above maximum %s, using default %s",
            name,
            raw,
            maximum,
            default,
        )
        return default
    return value


def get_float_env(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Safe float-from-env parser — same contract as get_int_env."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("invalid float env %s=%r, using default %s", name, raw, default)
        return default
    if minimum is not None and value < minimum:
        logger.warning("env %s=%r below minimum %s, using default %s", name, raw, minimum, default)
        return default
    if maximum is not None and value > maximum:
        logger.warning("env %s=%r above maximum %s, using default %s", name, raw, maximum, default)
        return default
    return value
