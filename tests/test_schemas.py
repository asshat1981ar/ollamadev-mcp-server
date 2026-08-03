"""Tests for type-safe tool input schemas."""

import pytest
from pydantic import ValidationError

from ollamadev_mcp_server.schemas import (
    CreateTaskInput,
    FindSymbolInput,
    GradleBuildInput,
    GradleTestInput,
    ListFilesInput,
    PhaseArtifactInput,
    Priority,
    PytestInput,
    ReadFileInput,
    SearchInput,
    ShellCommandInput,
    SprintPhase,
    SymbolType,
    UpdateSettingsInput,
    WriteFileInput,
)


class TestListFilesInput:
    def test_valid_input(self):
        input_data = ListFilesInput(root="app/src")
        assert input_data.root == "app/src"

    def test_empty_root(self):
        input_data = ListFilesInput(root="")
        assert input_data.root == ""

    def test_path_traversal_rejected(self):
        with pytest.raises(ValidationError, match="traversal"):
            ListFilesInput(root="../etc")


class TestReadFileInput:
    def test_valid_input(self):
        input_data = ReadFileInput(path="app/src/Main.kt")
        assert input_data.path == "app/src/Main.kt"

    def test_empty_path_rejected(self):
        with pytest.raises(ValidationError, match="empty"):
            ReadFileInput(path="")

    def test_path_traversal_rejected(self):
        with pytest.raises(ValidationError, match="traversal"):
            ReadFileInput(path="../etc/passwd")


class TestWriteFileInput:
    def test_valid_input(self):
        input_data = WriteFileInput(path="foo.kt", content="package com.example")
        assert input_data.path == "foo.kt"
        assert input_data.content == "package com.example"
        assert input_data.create_dirs is True

    def test_empty_path_rejected(self):
        with pytest.raises(ValidationError, match="empty"):
            WriteFileInput(path="", content="content")

    def test_path_traversal_rejected(self):
        with pytest.raises(ValidationError, match="traversal"):
            WriteFileInput(path="../etc/passwd", content="content")

    def test_large_content_rejected(self):
        large_content = "x" * (10 * 1024 * 1024 + 1)
        with pytest.raises(ValidationError, match="10MB"):
            WriteFileInput(path="foo.kt", content=large_content)


class TestSearchInput:
    def test_valid_input(self):
        input_data = SearchInput(pattern="class.*Test")
        assert input_data.pattern == "class.*Test"
        assert input_data.file_glob == "*.kt"
        assert input_data.ignore_case is False
        assert input_data.context_lines == 2

    def test_context_lines_bounds(self):
        with pytest.raises(ValidationError):
            SearchInput(pattern="test", context_lines=-1)
        with pytest.raises(ValidationError):
            SearchInput(pattern="test", context_lines=101)


class TestFindSymbolInput:
    def test_valid_input(self):
        input_data = FindSymbolInput(name="MyClass")
        assert input_data.name == "MyClass"
        assert input_data.symbol_type == SymbolType.ANY

    def test_symbol_type_enum(self):
        input_data = FindSymbolInput(name="foo", symbol_type=SymbolType.FUNCTION)
        assert input_data.symbol_type == SymbolType.FUNCTION


class TestCreateTaskInput:
    def test_valid_input(self):
        input_data = CreateTaskInput(title="Fix bug", tier="3", priority=Priority.HIGH)
        assert input_data.title == "Fix bug"
        assert input_data.tier == "3"
        assert input_data.priority == Priority.HIGH

    def test_tier_validation(self):
        with pytest.raises(ValidationError, match="between 1 and 5"):
            CreateTaskInput(title="Task", tier="0")
        with pytest.raises(ValidationError, match="between 1 and 5"):
            CreateTaskInput(title="Task", tier="6")

    def test_tier_non_integer_rejected(self):
        with pytest.raises(ValidationError, match="Invalid tier"):
            CreateTaskInput(title="Task", tier="abc")


class TestPhaseArtifactInput:
    def test_valid_input(self):
        input_data = PhaseArtifactInput(cycle_id=1, phase=SprintPhase.DISCOVERY)
        assert input_data.cycle_id == 1
        assert input_data.phase == SprintPhase.DISCOVERY

    def test_cycle_id_must_be_positive(self):
        with pytest.raises(ValidationError):
            PhaseArtifactInput(cycle_id=0, phase=SprintPhase.DISCOVERY)


class TestGradleTestInput:
    def test_valid_input(self):
        input_data = GradleTestInput(module="app", test_filter="*Test")
        assert input_data.module == "app"
        assert input_data.timeout_seconds == 600

    def test_timeout_bounds(self):
        with pytest.raises(ValidationError):
            GradleTestInput(timeout_seconds=5)
        with pytest.raises(ValidationError):
            GradleTestInput(timeout_seconds=4000)


class TestShellCommandInput:
    def test_valid_input(self):
        input_data = ShellCommandInput(command="ls -la")
        assert input_data.command == "ls -la"
        assert input_data.timeout_seconds == 300


class TestPytestInput:
    def test_valid_input(self):
        input_data = PytestInput(path="tests", test_filter="test_foo")
        assert input_data.path == "tests"
        assert input_data.test_filter == "test_foo"


class TestUpdateSettingsInput:
    def test_valid_input(self):
        input_data = UpdateSettingsInput(settings={"ollama_url": "http://localhost:11434"})
        assert input_data.settings["ollama_url"] == "http://localhost:11434"

    def test_unknown_key_rejected(self):
        with pytest.raises(ValidationError, match="Unknown setting keys"):
            UpdateSettingsInput(settings={"unknown_key": "value"})

    def test_empty_value_rejected(self):
        with pytest.raises(ValidationError, match="non-empty string"):
            UpdateSettingsInput(settings={"ollama_url": ""})

    def test_all_allowed_keys(self):
        settings = {
            "workspace_root": "/tmp",
            "ollama_url": "http://localhost:11434",
            "ollama_api_key": "key",
            "anthropic_api_key": "key",
            "anthropic_auth_token": "token",
            "anthropic_base_url": "https://api.anthropic.com",
            "default_cloud_model": "claude-sonnet-5-20251001",
        }
        input_data = UpdateSettingsInput(settings=settings)
        assert len(input_data.settings) == 7
