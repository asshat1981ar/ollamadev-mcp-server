"""Tests for tool module registry."""

from mcp.server import MCPServer

from ollamadev_mcp_server.registry import (
    ToolModule,
    ToolRegistry,
    get_registry,
    register_default_modules,
)


class TestToolModule:
    def test_tool_module_creation(self):
        class FakeModule:
            def register(self, mcp):
                pass

        mod = ToolModule(
            name="test",
            module=FakeModule(),
            register_fn=FakeModule.register,
            category="test",
            description="Test module",
        )
        assert mod.name == "test"
        assert mod.category == "test"
        assert mod.tool_count == 0


class TestToolRegistry:
    def test_register_module(self):
        class FakeModule:
            def register(self, mcp):
                pass

        registry = ToolRegistry()
        registry.register_module("test", FakeModule(), "test", "Test module")
        modules = registry.get_modules()
        assert len(modules) == 1
        assert modules[0].name == "test"

    def test_register_module_without_register_fn_raises(self):
        class BadModule:
            pass

        registry = ToolRegistry()
        try:
            registry.register_module("bad", BadModule(), "test", "Bad module")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "register()" in str(e)

    def test_register_all(self):
        class FakeModule:
            def __init__(self):
                self.registered = False

            def register(self, mcp):
                self.registered = True

        registry = ToolRegistry()
        mod = FakeModule()
        registry.register_module("test", mod, "test", "Test module")

        mcp = MCPServer("Test")
        registry.register_all(mcp)
        assert mod.registered

    def test_get_module(self):
        class FakeModule:
            def register(self, mcp):
                pass

        registry = ToolRegistry()
        registry.register_module("test", FakeModule(), "test", "Test module")
        mod = registry.get_module("test")
        assert mod is not None
        assert mod.name == "test"

    def test_get_module_not_found(self):
        registry = ToolRegistry()
        mod = registry.get_module("nonexistent")
        assert mod is None

    def test_get_modules_by_category(self):
        class FakeModule:
            def register(self, mcp):
                pass

        registry = ToolRegistry()
        registry.register_module("mod1", FakeModule(), "cat1", "Module 1")
        registry.register_module("mod2", FakeModule(), "cat1", "Module 2")
        registry.register_module("mod3", FakeModule(), "cat2", "Module 3")

        cat1_modules = registry.get_modules_by_category("cat1")
        assert len(cat1_modules) == 2

    def test_clear(self):
        class FakeModule:
            def register(self, mcp):
                pass

        registry = ToolRegistry()
        registry.register_module("test", FakeModule(), "test", "Test module")
        assert len(registry.get_modules()) == 1
        registry.clear()
        assert len(registry.get_modules()) == 0


class TestGetRegistry:
    def test_get_registry_returns_same_instance(self):
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2


class TestRegisterDefaultModules:
    def test_register_default_modules(self):
        registry = get_registry()
        registry.clear()
        register_default_modules()
        modules = registry.get_modules()
        assert len(modules) == 13  # 13 default modules

    def test_default_modules_have_correct_names(self):
        registry = get_registry()
        registry.clear()
        register_default_modules()
        module_names = {mod.name for mod in registry.get_modules()}
        expected = {
            "filesystem",
            "code",
            "build",
            "sprint",
            "memory",
            "meta",
            "patch",
            "git_tools",
            "dependencies",
            "observability",
            "sandbox",
            "settings",
            "cloudflare_computer",
        }
        assert module_names == expected

    def test_default_modules_have_categories(self):
        registry = get_registry()
        registry.clear()
        register_default_modules()
        for mod in registry.get_modules():
            assert mod.category, f"Module {mod.name} has no category"

    def test_default_modules_have_descriptions(self):
        registry = get_registry()
        registry.clear()
        register_default_modules()
        for mod in registry.get_modules():
            assert mod.description, f"Module {mod.name} has no description"
