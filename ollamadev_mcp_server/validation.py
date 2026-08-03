"""Input validation utilities for MCP tool arguments.

Provides reusable validators that raise ``ValidationError`` on bad input.
All validators are pure functions — no side effects.

Usage::

    from ollamadev_mcp_server.validation import validate_path, validate_content

    validate_path("app/src/main/kotlin/Foo.kt")  # OK
    validate_path("../../../etc/passwd")          # raises ValidationError
"""

import re

from ollamadev_mcp_server.errors import ValidationError
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_PATH_LENGTH = 1024
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
MAX_PATTERN_LENGTH = 4096
MAX_TOOL_ARGUMENT_SIZE = 1 * 1024 * 1024  # 1 MB

# ---------------------------------------------------------------------------
# Dangerous path patterns
# ---------------------------------------------------------------------------

_DANGEROUS_PATH_PATTERNS = [
    (re.compile(r"\.\.[\\\\/]"), "path traversal (..)"),
    (re.compile(r"[\x00-\x1f]"), "control characters"),
]


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_path(path: str, *, allow_absolute: bool = False) -> str:
    """Validate a relative path argument.

    Raises ``ValidationError`` if the path is empty, too long, contains
    traversal sequences, or control characters.
    """
    if not path:
        raise ValidationError("Path cannot be empty", field="path")
    if len(path) > MAX_PATH_LENGTH:
        raise ValidationError(
            f"Path too long: {len(path)} > {MAX_PATH_LENGTH}",
            field="path",
            length=len(path),
        )
    if not allow_absolute and path.startswith(("/", "\\\\")):
        raise ValidationError(
            "Absolute paths are not allowed",
            field="path",
        )
    for pattern, description in _DANGEROUS_PATH_PATTERNS:
        if pattern.search(path):
            raise ValidationError(
                f"Invalid path: {description}",
                field="path",
            )
    return path


def validate_content(content: str, *, max_length: int = MAX_CONTENT_LENGTH) -> str:
    """Validate file content before writing.

    Raises ``ValidationError`` if the content exceeds the size limit or
    contains null bytes.
    """
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > max_length:
        raise ValidationError(
            f"Content too large: {len(content_bytes)} bytes > {max_length} bytes",
            field="content",
            size=len(content_bytes),
        )
    if "\x00" in content:
        raise ValidationError(
            "Content contains null bytes (binary content not allowed)",
            field="content",
        )
    return content


def validate_pattern(pattern: str) -> str:
    """Validate a regex pattern argument.

    Raises ``ValidationError`` if the pattern is empty, too long, or
    contains invalid regex syntax.
    """
    if not pattern:
        raise ValidationError("Pattern cannot be empty", field="pattern")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValidationError(
            f"Pattern too long: {len(pattern)} > {MAX_PATTERN_LENGTH}",
            field="pattern",
            length=len(pattern),
        )
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValidationError(
            f"Invalid regex pattern: {exc}",
            field="pattern",
        ) from exc
    return pattern


def validate_positive_int(
    value: int,
    *,
    name: str,
    min_value: int = 0,
    max_value: int = 100_000,
) -> int:
    """Validate a positive integer argument.

    Raises ``ValidationError`` if the value is out of range.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(
            f"{name} must be an integer",
            field=name,
        )
    if value < min_value:
        raise ValidationError(
            f"{name} must be >= {min_value}, got {value}",
            field=name,
        )
    if value > max_value:
        raise ValidationError(
            f"{name} must be <= {max_value}, got {value}",
            field=name,
        )
    return value


def validate_enum(
    value: str,
    *,
    name: str,
    allowed: list[str] | tuple[str, ...],
) -> str:
    """Validate that a string is one of the allowed values.

    Raises ``ValidationError`` if the value is not in the allowed set.
    """
    if value not in allowed:
        raise ValidationError(
            f"{name} must be one of: {', '.join(allowed)}",
            field=name,
            value=value,
        )
    return value
