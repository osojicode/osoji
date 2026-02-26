"""Shared pytest fixtures for docstar tests."""

import shutil
import tempfile
from pathlib import Path

import pytest

from docstar.walker import clear_repo_files_cache


def pytest_addoption(parser):
    parser.addoption(
        "--establish-baseline",
        action="store_true",
        default=False,
        help="Run prompt regression tests in baseline establishment mode",
    )


@pytest.fixture
def establish_baseline(request):
    return request.config.getoption("--establish-baseline")


@pytest.fixture(autouse=True)
def _clear_repo_files_cache():
    """Clear the git ls-files cache before and after each test."""
    clear_repo_files_cache()
    yield
    clear_repo_files_cache()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    dir_path = Path(tempfile.mkdtemp())
    yield dir_path
    shutil.rmtree(dir_path, ignore_errors=True)


