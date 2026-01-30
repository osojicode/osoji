"""Shared pytest fixtures for docstar tests."""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    dir_path = Path(tempfile.mkdtemp())
    yield dir_path
    shutil.rmtree(dir_path, ignore_errors=True)


@pytest.fixture
def temp_git_repo(temp_dir):
    """Create a temporary git repository."""
    subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=temp_dir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=temp_dir,
        capture_output=True,
        check=True,
    )
    yield temp_dir


@pytest.fixture
def sample_file_with_path(temp_dir):
    """Create a sample file containing a personal path."""
    file_path = temp_dir / "config.py"
    file_path.write_text('DATABASE_PATH = "C:\\Users\\johnf\\data\\db.sqlite"\n')
    return file_path


@pytest.fixture
def sample_clean_file(temp_dir):
    """Create a sample file with no personal paths."""
    file_path = temp_dir / "clean.py"
    file_path.write_text('import os\nprint("Hello, world!")\n')
    return file_path
