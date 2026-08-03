"""Input sanitization for the OllamaDev MCP server.

Provides enhanced path validation, filename sanitization, and content
checks that go beyond the basic ``_safe_path`` in ``filesystem.py``.

Usage::

    from ollamadev_mcp_server.sanitization import sanitize_path

    target = sanitize_path("app/src/Foo.kt", workspace_root=WORKSPACE_ROOT)
"""

import os
import re
from pathlib import Path

from ollamadev_mcp_server.errors import SecurityError, ValidationError
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Dangerous patterns
# ---------------------------------------------------------------------------

_NULL_BYTE = re.compile(r"\x00")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_PATH_TRAVERSAL = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")


# ---------------------------------------------------------------------------
# Path sanitization
# ---------------------------------------------------------------------------


def sanitize_path(path: str, *, workspace_root: Path) -> Path:
    """Sanitize and validate a relative path within the workspace.

    Raises ``SecurityError`` on traversal attempts, null bytes, or
    paths that escape the workspace after resolution.
    """
    if not path:
        raise ValidationError("Path cannot be empty", field="path")

    # Null bytes
    if _NULL_BYTE.search(path):
        raise SecurityError("Path contains null bytes", field="path")

    # Control characters
    if _CONTROL_CHARS.search(path):
        raise SecurityError("Path contains control characters", field="path")

    # Traversal sequences
    if _PATH_TRAVERSAL.search(path):
        raise SecurityError(f"Path traversal detected: {path!r}", field="path")

    # Resolve and verify containment
    target = (workspace_root / path).resolve()
    workspace = workspace_root.resolve()

    try:
        common = os.path.commonpath([str(target), str(workspace)])
        if common != str(workspace):
            raise SecurityError(f"Path escapes workspace: {path!r}", field="path")
    except ValueError:
        # Different drives on Windows
        raise SecurityError(f"Path on different drive: {path!r}", field="path")

    return target


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------


def sanitize_filename(filename: str) -> str:
    """Sanitize a bare filename (no directory components).

    Strips path separators, null bytes, control characters, and leading
    dots.  Raises ``ValidationError`` if the result is empty.
    """
    name = filename.replace("/", "_").replace("\\", "_")
    name = _NULL_BYTE.sub("", name)
    name = _CONTROL_CHARS.sub("", name)
    name = name.lstrip(".")
    if len(name) > 255:
        name = name[:255]
    if not name:
        raise ValidationError("Invalid filename", field="filename")
    return name


# ---------------------------------------------------------------------------
# Content sanitization
# ---------------------------------------------------------------------------


def validate_file_content(content: str, *, max_size: int = 10 * 1024 * 1024) -> None:
    """Validate file content before writing.

    Raises ``ValidationError`` if the content exceeds *max_size* bytes
    or contains null bytes.
    """
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > max_size:
        raise ValidationError(
            f"Content too large: {len(content_bytes)} bytes > {max_size} bytes",
            field="content",
            size=len(content_bytes),
        )
    if "\x00" in content:
        raise ValidationError("Content contains null bytes", field="content")


# ---------------------------------------------------------------------------
# Shell command masking (for logging only)
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERN = re.compile(
    r"(api[_-]?key|token|password|secret)\s*[=:]\s*\S+",
    re.IGNORECASE,
)


def mask_sensitive_in_command(command: str) -> str:
    """Mask sensitive values in a shell command string (for safe logging)."""
    return _SENSITIVE_PATTERN.sub(r"\1=***", command)
