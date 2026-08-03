"""Tests for input validation utilities."""

import pytest

from ollamadev_mcp_server.errors import ValidationError
from ollamadev_mcp_server.validation import (
    MAX_CONTENT_LENGTH,
    MAX_PATH_LENGTH,
    MAX_PATTERN_LENGTH,
    validate_content,
    validate_enum,
    validate_path,
    validate_pattern,
    validate_positive_int,
)


class TestValidatePath:
    def test_valid_relative_path(self):
        assert validate_path("app/src/main/kotlin/Foo.kt") == "app/src/main/kotlin/Foo.kt"

    def test_empty_path_raises(self):
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_path("")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError, match="too long"):
            validate_path("a" * (MAX_PATH_LENGTH + 1))

    def test_absolute_path_raises(self):
        with pytest.raises(ValidationError, match="Absolute"):
            validate_path("/etc/passwd")

    def test_traversal_raises(self):
        with pytest.raises(ValidationError, match="traversal"):
            validate_path("../etc/passwd")

    def test_control_chars_raise(self):
        with pytest.raises(ValidationError, match="control"):
            validate_path("foo\x00bar")

    def test_allow_absolute(self):
        assert validate_path("/etc/passwd", allow_absolute=True) == "/etc/passwd"


class TestValidateContent:
    def test_valid_content(self):
        assert validate_content("hello world") == "hello world"

    def test_too_large_raises(self):
        with pytest.raises(ValidationError, match="too large"):
            validate_content("x" * (MAX_CONTENT_LENGTH + 1))

    def test_null_bytes_raise(self):
        with pytest.raises(ValidationError, match="null bytes"):
            validate_content("hello\x00world")

    def test_custom_max_length(self):
        with pytest.raises(ValidationError, match="too large"):
            validate_content("x" * 100, max_length=50)


class TestValidatePattern:
    def test_valid_pattern(self):
        assert validate_pattern(r"class\s+\w+") == r"class\s+\w+"

    def test_empty_raises(self):
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_pattern("")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError, match="too long"):
            validate_pattern("x" * (MAX_PATTERN_LENGTH + 1))

    def test_invalid_regex_raises(self):
        with pytest.raises(ValidationError, match="Invalid regex"):
            validate_pattern("[unclosed")


class TestValidatePositiveInt:
    def test_valid(self):
        assert validate_positive_int(5, name="count") == 5

    def test_zero_valid(self):
        assert validate_positive_int(0, name="count") == 0

    def test_negative_raises(self):
        with pytest.raises(ValidationError, match="must be >= 0"):
            validate_positive_int(-1, name="count")

    def test_too_large_raises(self):
        with pytest.raises(ValidationError, match="must be <="):
            validate_positive_int(200000, name="count")

    def test_non_int_raises(self):
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_positive_int("5", name="count")

    def test_bool_raises(self):
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_positive_int(True, name="count")

    def test_custom_range(self):
        assert validate_positive_int(5, name="x", min_value=1, max_value=10) == 5


class TestValidateEnum:
    def test_valid(self):
        assert validate_enum("low", name="priority", allowed=["low", "medium", "high"]) == "low"

    def test_invalid_raises(self):
        with pytest.raises(ValidationError, match="must be one of"):
            validate_enum("urgent", name="priority", allowed=["low", "medium", "high"])
