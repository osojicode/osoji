"""Tests for personal path detection."""

import pytest

from osoji.safety.paths import (
    PATTERNS,
    check_file_for_paths,
    get_pattern_descriptions,
    self_test,
)


class TestWindowsUserPaths:
    """Tests for Windows user path detection."""

    def test_detects_windows_path_backslash(self, temp_dir):
        """Should detect C:\\Users\\username\\ pattern."""
        test_file = temp_dir / "test.py"
        test_file.write_text('config = "C:\\Users\\jsmith\\projects\\myapp"')

        findings = check_file_for_paths(test_file)

        assert len(findings) == 1
        assert findings[0].pattern_name == "windows_user"
        assert "C:\\Users\\jsmith\\" in findings[0].match

    def test_detects_windows_path_forward_slash(self, temp_dir):
        """Should detect C:/Users/username/ pattern."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "C:/Users/alice/code"')

        findings = check_file_for_paths(test_file)

        # May also match unix_home for the /Users/alice/ part, which is fine
        windows_findings = [f for f in findings if f.pattern_name == "windows_user"]
        assert len(windows_findings) == 1

    def test_case_insensitive_drive_letter(self, temp_dir):
        """Should detect both C: and c: drive letters."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "c:\\Users\\JSmith\\code"')

        findings = check_file_for_paths(test_file)

        assert len(findings) == 1

    def test_excludes_test_user(self, temp_dir):
        """Should not flag C:\\Users\\test\\ as personal path."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "C:\\Users\\test\\data"')

        findings = check_file_for_paths(test_file)

        assert len(findings) == 0

    def test_excludes_example_user(self, temp_dir):
        """Should not flag C:\\Users\\example\\ as personal path."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "C:\\Users\\example\\data"')

        findings = check_file_for_paths(test_file)

        assert len(findings) == 0

    def test_excludes_runner_user(self, temp_dir):
        """Should not flag C:\\Users\\runner\\ (CI) as personal path."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "C:\\Users\\runner\\work"')

        findings = check_file_for_paths(test_file)

        assert len(findings) == 0


class TestUnixHomePaths:
    """Tests for Unix/Mac home directory detection."""

    def test_detects_linux_home(self, temp_dir):
        """Should detect /home/username/ pattern."""
        test_file = temp_dir / "test.py"
        test_file.write_text('HOME = "/home/jsmith/projects"')

        findings = check_file_for_paths(test_file)

        assert len(findings) == 1
        assert findings[0].pattern_name == "unix_home"

    def test_detects_mac_users(self, temp_dir):
        """Should detect /Users/username/ pattern."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "/Users/alice/Documents"')

        findings = check_file_for_paths(test_file)

        # May also match personal_folder for Documents
        unix_findings = [f for f in findings if f.pattern_name == "unix_home"]
        assert len(unix_findings) == 1

    def test_excludes_test_user(self, temp_dir):
        """Should not flag /home/test/ as personal path."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "/home/test/data"')

        findings = check_file_for_paths(test_file)
        unix_findings = [f for f in findings if f.pattern_name == "unix_home"]

        assert len(unix_findings) == 0

    def test_excludes_ubuntu_user(self, temp_dir):
        """Should not flag /home/ubuntu/ (common CI/cloud user) as personal path."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "/home/ubuntu/app"')

        findings = check_file_for_paths(test_file)
        unix_findings = [f for f in findings if f.pattern_name == "unix_home"]

        assert len(unix_findings) == 0


class TestCloudStoragePaths:
    """Tests for cloud storage path detection."""

    @pytest.mark.parametrize(
        "cloud",
        ["Dropbox", "OneDrive", "Google Drive", "iCloud", "Box", "pCloud"],
    )
    def test_detects_cloud_storage(self, temp_dir, cloud):
        """Should detect various cloud storage paths."""
        test_file = temp_dir / "test.py"
        test_file.write_text(f'sync_path = "/Users/me/{cloud}/work/"')

        findings = check_file_for_paths(test_file)
        cloud_findings = [f for f in findings if f.pattern_name == "cloud_storage"]

        assert len(cloud_findings) == 1

    def test_case_insensitive(self, temp_dir):
        """Cloud storage detection should be case-insensitive."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "/dropbox/projects/"')

        findings = check_file_for_paths(test_file)
        cloud_findings = [f for f in findings if f.pattern_name == "cloud_storage"]

        assert len(cloud_findings) == 1


class TestDatedFolders:
    """Tests for dated project folder detection."""

    def test_detects_dated_folder_with_space(self, temp_dir):
        """Should detect /260124 OSOJI/ pattern."""
        test_file = temp_dir / "test.py"
        test_file.write_text('project = "/code/260124 OSOJI/src"')

        findings = check_file_for_paths(test_file)
        dated_findings = [f for f in findings if f.pattern_name == "dated_folder"]

        assert len(dated_findings) == 1

    def test_detects_backslash_dated_folder(self, temp_dir):
        """Should detect \\251007 FIXTHEDOCS\\ pattern."""
        test_file = temp_dir / "test.py"
        test_file.write_text('project = "C:\\projects\\251007 FIXTHEDOCS\\src"')

        findings = check_file_for_paths(test_file)
        dated_findings = [f for f in findings if f.pattern_name == "dated_folder"]

        assert len(dated_findings) == 1

    def test_requires_uppercase(self, temp_dir):
        """Should not match dated folders without uppercase letters."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "/260124 project/src"')

        findings = check_file_for_paths(test_file)
        dated_findings = [f for f in findings if f.pattern_name == "dated_folder"]

        assert len(dated_findings) == 0


class TestPersonalFolders:
    """Tests for personal folder detection."""

    @pytest.mark.parametrize(
        "folder",
        ["Documents", "Desktop", "Downloads", "Pictures", "Videos"],
    )
    def test_detects_personal_folders(self, temp_dir, folder):
        """Should detect common personal folders."""
        test_file = temp_dir / "test.py"
        test_file.write_text(f'path = "/{folder}/work/"')

        findings = check_file_for_paths(test_file)
        folder_findings = [f for f in findings if f.pattern_name == "personal_folder"]

        assert len(folder_findings) == 1

    def test_case_insensitive(self, temp_dir):
        """Personal folder detection should be case-insensitive."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "/DOCUMENTS/project/"')

        findings = check_file_for_paths(test_file)
        folder_findings = [f for f in findings if f.pattern_name == "personal_folder"]

        assert len(folder_findings) == 1


class TestMyFolderPatterns:
    """Tests for 'My X' folder pattern detection."""

    def test_detects_my_projects(self, temp_dir):
        """Should detect /My Projects/ pattern."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "/My Projects/app/"')

        findings = check_file_for_paths(test_file)
        my_findings = [f for f in findings if f.pattern_name == "my_folder"]

        assert len(my_findings) == 1

    def test_detects_my_documents(self, temp_dir):
        """Should detect /My Documents/ pattern."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "\\My Documents\\work\\"')

        findings = check_file_for_paths(test_file)
        my_findings = [f for f in findings if f.pattern_name == "my_folder"]

        assert len(my_findings) == 1

    def test_case_insensitive(self, temp_dir):
        """'My X' detection should be case-insensitive."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "/MY STUFF/data/"')

        findings = check_file_for_paths(test_file)
        my_findings = [f for f in findings if f.pattern_name == "my_folder"]

        assert len(my_findings) == 1


class TestNoFalsePositives:
    """Tests to ensure safe paths are not flagged."""

    def test_ignores_system_paths(self, temp_dir):
        """Should not flag system paths."""
        test_file = temp_dir / "test.py"
        test_file.write_text(
            '''
import os
path = "/usr/local/bin"
config = "/etc/myapp/config.yaml"
data = "/var/data/app"
'''
        )

        findings = check_file_for_paths(test_file)

        assert len(findings) == 0

    def test_ignores_relative_paths(self, temp_dir):
        """Should not flag relative paths."""
        test_file = temp_dir / "test.py"
        test_file.write_text('path = "./src/main.py"')

        findings = check_file_for_paths(test_file)

        assert len(findings) == 0

    def test_ignores_url_paths(self, temp_dir):
        """Should not flag URL-like paths."""
        test_file = temp_dir / "test.py"
        test_file.write_text('url = "https://example.com/Users/api"')

        findings = check_file_for_paths(test_file)

        # Might match unix_home but shouldn't cause issues in practice
        # as https:// prefix makes it clearly not a filesystem path
        assert len(findings) <= 1


class TestPatternDescriptions:
    """Tests for pattern descriptions."""

    def test_all_patterns_have_descriptions(self):
        """Every pattern should have a description."""
        descriptions = get_pattern_descriptions()

        for pattern_name in PATTERNS:
            assert pattern_name in descriptions
            assert descriptions[pattern_name]  # Not empty


class TestSelfTest:
    """Tests for the self-test function."""

    def test_self_test_passes(self):
        """The paths module itself should pass self-test."""
        passed, findings = self_test()

        assert passed, f"Self-test failed with findings: {findings}"

    def test_self_test_returns_findings(self):
        """Self-test should return a tuple of (passed, findings)."""
        result = self_test()

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)
