"""Secret detection using detect-secrets (optional dependency).

This module wraps the detect-secrets library to scan files for potential
secrets like API keys, passwords, and private keys. If detect-secrets
is not installed, all functions gracefully degrade to no-ops.

Install with: pip install 'osoji[safety]'
"""

import logging
from pathlib import Path

from .models import SecretFinding

# Optional dependency - graceful degradation
try:
    from detect_secrets import SecretsCollection
    from detect_secrets.settings import default_settings

    HAS_DETECT_SECRETS = True
except ImportError:
    HAS_DETECT_SECRETS = False
    SecretsCollection = None  # type: ignore
    default_settings = None  # type: ignore

logger = logging.getLogger(__name__)
_warned_not_installed = False


def is_available() -> bool:
    """Check if detect-secrets is installed.

    Returns:
        True if detect-secrets is available for use
    """
    return HAS_DETECT_SECRETS


def check_file_for_secrets(file_path: Path) -> list[SecretFinding]:
    """Scan a file for potential secrets using detect-secrets.

    Args:
        file_path: Path to the file to scan

    Returns:
        List of SecretFinding objects. Empty if detect-secrets not installed.
    """
    global _warned_not_installed

    if not HAS_DETECT_SECRETS:
        if not _warned_not_installed:
            logger.debug(
                "detect-secrets not installed, skipping secret detection. "
                "Install with: pip install 'osoji[safety]'"
            )
            _warned_not_installed = True
        return []

    findings: list[SecretFinding] = []

    try:
        secrets = SecretsCollection()
        with default_settings():
            secrets.scan_file(str(file_path))

        # Iterate over the secrets collection
        # The data structure is: {filename: [PotentialSecret, ...]}
        for _filename, secret_list in secrets.data.items():
            for secret in secret_list:
                findings.append(
                    SecretFinding(
                        file=file_path,
                        line_number=secret.line_number,
                        secret_type=secret.type,
                    )
                )
    except Exception as e:
        # Log but don't fail - file might be binary, inaccessible, or
        # detect-secrets might have an internal error
        logger.debug(f"Error scanning {file_path} for secrets: {e}")

    return findings
