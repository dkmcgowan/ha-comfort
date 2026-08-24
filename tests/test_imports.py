"""Import every module in the integration.

This exists because a circular import shipped in 1.9.0 and got all the way
to a real Home Assistant before anything noticed. `ruff` does not detect
import cycles, and `compileall` compiles without importing, so both were
green. The only thing that catches it is actually importing the modules,
which needs Home Assistant present and therefore only runs in CI.

Home Assistant loads each platform module separately, so a cycle between
two platform modules only surfaces at load time. Importing them one at a
time here reproduces that.
"""

import importlib

import pytest

# Every module here pulls in Home Assistant, which cannot be imported on
# Windows. Skipping keeps a local run green while CI, on Ubuntu with Home
# Assistant installed, still enforces this.
pytest.importorskip("homeassistant", reason="Home Assistant is not importable here")

MODULES = [
    "api",
    "binary_sensor",
    "button",
    "climate",
    "command_cache",
    "config_flow",
    "const",
    "coordinator",
    "diagnostics",
    "entity",
    "last_hvac_mode",
    "push",
    "schedule",
    "sensor",
    "services",
    "temperature",
    "whole_home",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    """Each module imports on its own, in any order."""
    importlib.import_module(f"custom_components.kumo_cloud.{module}")


def test_platform_modules_import_in_isolation():
    """A platform must not depend on another platform being imported first.

    This is the exact shape of the 1.9.0 failure: `climate` imported
    `whole_home`, which imported `climate` back. Importing `whole_home`
    before `climate` makes the cycle fail loudly.
    """
    importlib.import_module("custom_components.kumo_cloud.whole_home")
    importlib.import_module("custom_components.kumo_cloud.climate")


def test_package_imports():
    """The integration package itself imports, with its platform list."""
    package = importlib.import_module("custom_components.kumo_cloud")
    assert package.PLATFORMS
