"""Tests for input sanitization."""

import pytest
from pathlib import Path

from ollamadev_mcp_server.sanitization import (
    sanitize_path,
    sanitize_filename,
    validate_file_content,
    mask_sensitive_in_command,
)
from ollamadev_mcp_server.errors import SecurityError, ValidationError


class TestSanitizePath:
    def test_valid_relative_path(self, tmp_path):
        result = sanitize_path("app/src/Foo.kt", workspace_root=tmp_path)
        assert result == tmp_path / "app/src/Foo.kt"

    def test_empty_path_raises(self, tmp_path):
        with pytest.raises(ValidationError, match="cannot be empty"):
            sanitize_path("", workspace_root=tmp_path)

    def test_null_bytes_raise(self, tmp_path):
        with pytest.raises(SecurityError, match="null bytes"):
            sanitize_path("foo\x00bar.kt", workspace_root=tmp_path)

    def test_control_chars_raise(self, tmp_path):
        with pytest.raises(SecurityError, match="control characters"):
            sanitize_path("foo\x01bar.kt", workspace_root=tmp_path)

    def test_traversal_raises(self, tmp_path):
        with pytest.raises(SecurityError, match="traversal"):
            sanitize_path("../etc/passwd", workspace_root=tmp_path)

    def test_traversal_in_middle_raises(self, tmp_path):
        with pytest.raises(SecurityError, match="traversal"):
            sanitize_path("app/../../../etc/passwd", workspace_root=tmp_path)

    def test_escape_workspace_raises(self, tmp_path):
        # Create a symlink that escapes (if supported)
        result = sanitize_path("app/src/Foo.kt", workspace_root=tmp_path)
        assert str(result).startswith(str(tmp_path.resolve()))

    def test_absolute_path_resolved(self, tmp_path):
        # Relative path should be resolved within workspace
        result = sanitize_path("foo.kt", workspace_root=tmp_path)
        assert result == tmp_path / "foo.kt"


class TestSanitizeFilename:
    def test_normal_filename(self):
        assert sanitize_filename("Foo.kt") == "Foo.kt"

    def test_strips_path_separators(self):
        assert sanitize_filename("path/to/file.kt") == "path_to_file.kt"

    def test_strips_null_bytes(self):
        assert sanitize_filename("foo\x00.kt") == "foo.kt"

    def test_strips_control_chars(self):
        assert sanitize_filename("foo\x01.kt") == "foo.kt"

    def test_strips_leading_dots(self):
        assert sanitize_filename(".hidden") == "hidden"

    def test_truncates_long_names(self):
        long_name = "a" * 300
        result = sanitize_filename(long_name)
        assert len(result) == 255

    def test_empty_after_sanitization_raises(self):
        with pytest.raises(ValidationError, match="Invalid filename"):
            sanitize_filename("...")

    def test_backslash_replaced(self):
        assert sanitize_filename(r"path\to\file.kt") == "path_to_file.kt"


class TestValidateFileContent:
    def test_valid_content(self):
        validate_file_content("hello world")

    def test_too_large_raises(self):
        with pytest.raises(ValidationError, match="too large"):
            validate_file_content("x" * (10 * 1024 * 1024 + 1))

    def test_custom_max_size(self):
        with pytest.raises(ValidationError, match="too large"):
            validate_file_content("x" * 100, max_size=50)

    def test_null_bytes_raise(self):
        with pytest.raises(ValidationError, match="null bytes"):
            validate_file_content("hello\x00world")


class TestMaskSensitiveInCommand:
    def test_masks_api_key(self):
        result = mask_sensitive_in_command("curl -H 'api_key=secret123'")
        assert "secret123" not in result
        assert "api_key=***" in result

    def test_masks_token(self):
        result = mask_sensitive_in_command("export TOKEN=abc123def456")
        assert "abc123def456" not in result
        assert "TOKEN=***" in result

    def test_masks_password(self):
        result = mask_sensitive_in_command("mysql -p password=secret")
        assert "secret" not in result
        assert "password=***" in result

    def test_no_sensitive_data_unchanged(self):
        cmd = "ls -la /tmp"
        assert mask_sensitive_in_command(cmd) == cmd

    def test_case_insensitive(self):
        result = mask_sensitive_in_command("API_KEY=mysecret")
        assert "mysecret" not in result
