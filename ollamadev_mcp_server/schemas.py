"""Type-safe tool input schemas using Pydantic.

Provides Pydantic models for validating tool inputs at the schema level
rather than inside tool functions.  Makes validation declarative and
reusable.

Usage::

    from ollamadev_mcp_server.schemas import WriteFileInput

    input_data = WriteFileInput(path="foo.kt", content="package com.example")
    # Raises ValidationError if path or content are invalid
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SprintPhase(str, Enum):
    """Sprint phase names."""

    DISCOVERY = "discovery"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    INTEGRATION = "integration"
    RETROSPECTIVE = "retrospective"


class Priority(str, Enum):
    """Task priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SymbolType(str, Enum):
    """Symbol types for code search."""

    ANY = "any"
    CLASS = "class"
    FUNCTION = "function"
    PROPERTY = "property"


class ScreenshotMode(str, Enum):
    """Screenshot test modes."""

    RECORD = "record"
    VERIFY = "verify"


class TranscriptFormat(str, Enum):
    """Transcript output formats."""

    MARKDOWN = "markdown"
    JSON = "json"


# ---------------------------------------------------------------------------
# Filesystem schemas
# ---------------------------------------------------------------------------


class ListFilesInput(BaseModel):
    """Input for list_workspace_files tool."""

    root: str = Field(default="", description="Sub-path within workspace to list")

    @field_validator("root")
    @classmethod
    def validate_root(cls, v: str) -> str:
        if ".." in v:
            raise ValueError("Path traversal not allowed")
        return v


class ReadFileInput(BaseModel):
    """Input for read_workspace_file tool."""

    path: str = Field(description="Relative path to file")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not v:
            raise ValueError("Path cannot be empty")
        if ".." in v:
            raise ValueError("Path traversal not allowed")
        return v


class WriteFileInput(BaseModel):
    """Input for write_workspace_file tool."""

    path: str = Field(description="Relative path to file")
    content: str = Field(description="File content")
    create_dirs: bool = Field(default=True, description="Create parent directories")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not v:
            raise ValueError("Path cannot be empty")
        if ".." in v:
            raise ValueError("Path traversal not allowed")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 10 * 1024 * 1024:
            raise ValueError("Content exceeds 10MB limit")
        return v


# ---------------------------------------------------------------------------
# Code intelligence schemas
# ---------------------------------------------------------------------------


class SearchInput(BaseModel):
    """Input for search_workspace tool."""

    pattern: str = Field(description="Regex pattern to search for")
    file_glob: str = Field(default="*.kt", description="File glob pattern")
    ignore_case: bool = Field(default=False, description="Case-insensitive search")
    context_lines: int = Field(
        default=2, ge=0, le=100, description="Context lines around matches"
    )


class FindSymbolInput(BaseModel):
    """Input for find_symbol tool."""

    name: str = Field(description="Symbol name to find")
    symbol_type: SymbolType = Field(default=SymbolType.ANY, description="Type of symbol")
    file_glob: str = Field(default="*.kt", description="File glob pattern")


# ---------------------------------------------------------------------------
# Sprint schemas
# ---------------------------------------------------------------------------


class CreateTaskInput(BaseModel):
    """Input for create_sprint_task tool."""

    title: str = Field(description="Task title")
    description: str = Field(default="", description="Task description")
    tier: str = Field(default="3", description="Task tier (1-5)")
    priority: Priority = Field(default=Priority.MEDIUM, description="Task priority")

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: str) -> str:
        try:
            tier_int = int(v)
            if tier_int < 1 or tier_int > 5:
                raise ValueError("Tier must be between 1 and 5")
        except ValueError as e:
            if "between 1 and 5" in str(e):
                raise
            raise ValueError(f"Invalid tier: {v}") from e
        return v


class PhaseArtifactInput(BaseModel):
    """Input for phase artifact tools."""

    cycle_id: int = Field(ge=1, description="Sprint cycle ID")
    phase: SprintPhase = Field(description="Sprint phase")


class EvaluateOutcomeInput(BaseModel):
    """Input for evaluate_sprint_outcome tool."""

    cycle_id: int = Field(ge=1, description="Sprint cycle ID")
    phase: SprintPhase = Field(description="Sprint phase to evaluate")


# ---------------------------------------------------------------------------
# Build schemas
# ---------------------------------------------------------------------------


class GradleTestInput(BaseModel):
    """Input for run_gradle_tests tool."""

    module: str = Field(default="app", description="Gradle module")
    test_filter: str = Field(default="", description="Test class filter")
    timeout_seconds: int = Field(
        default=600, ge=10, le=3600, description="Timeout in seconds"
    )


class GradleBuildInput(BaseModel):
    """Input for run_gradle_build tool."""

    module: str = Field(default="app", description="Gradle module")
    variant: str = Field(default="Debug", description="Build variant")
    timeout_seconds: int = Field(
        default=600, ge=10, le=3600, description="Timeout in seconds"
    )


# ---------------------------------------------------------------------------
# Sandbox schemas
# ---------------------------------------------------------------------------


class ShellCommandInput(BaseModel):
    """Input for run_shell_command tool."""

    command: str = Field(description="Shell command to execute")
    timeout_seconds: int = Field(
        default=300, ge=1, le=3600, description="Timeout in seconds"
    )


class PytestInput(BaseModel):
    """Input for run_pytest tool."""

    path: str = Field(default="", description="Directory or file to test")
    test_filter: str = Field(default="", description="pytest -k filter")
    timeout_seconds: int = Field(
        default=300, ge=10, le=3600, description="Timeout in seconds"
    )


# ---------------------------------------------------------------------------
# Settings schemas
# ---------------------------------------------------------------------------


class UpdateSettingsInput(BaseModel):
    """Input for update_server_settings tool."""

    settings: dict[str, str] = Field(description="Settings key-value pairs")

    @field_validator("settings")
    @classmethod
    def validate_settings(cls, v: dict[str, str]) -> dict[str, str]:
        allowed_keys = {
            "workspace_root",
            "ollama_url",
            "ollama_api_key",
            "anthropic_api_key",
            "anthropic_auth_token",
            "anthropic_base_url",
            "default_cloud_model",
        }
        unknown = set(v.keys()) - allowed_keys
        if unknown:
            raise ValueError(f"Unknown setting keys: {sorted(unknown)}")
        for key, value in v.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Setting '{key}' must be a non-empty string")
        return v
