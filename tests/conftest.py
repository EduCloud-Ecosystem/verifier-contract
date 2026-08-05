"""Shared fixtures. Nothing here reaches the network or calls a model."""

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def runner():
    """The conformance runner, loaded by path — it is a tool, not a package."""
    return _load("conformance_runner", ROOT / "conformance" / "runner.py")


@pytest.fixture
def science():
    """A FRESH science module per test.

    Reloading matters: `register_resolver` mutates module state, and a test that
    installs a resolver must not be able to leak it into the test that asserts
    the live resolver is not installed.
    """
    return _load("science_under_test", ROOT / "profiles" / "science.py")
