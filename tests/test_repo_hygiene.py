"""Guards for repo conventions that are easy to break by accident."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=ROOT, check=False, capture_output=True
    )
    return result.returncode == 0


def test_personal_files_are_git_ignored():
    for path in ("TODO.md", ".env"):
        assert _is_ignored(path), f"{path} must be listed in .gitignore"


def test_tracking_docs_exist():
    for path in ("docs/blueprint.md", "docs/STATUS.md", "docs/adr/0000-template.md", "CLAUDE.md"):
        assert (ROOT / path).is_file(), f"missing {path}"


def test_status_has_required_sections():
    text = (ROOT / "docs/STATUS.md").read_text()
    for heading in ("## Current focus", "## Next up", "## Blockers", "## Session log"):
        assert heading in text, f"docs/STATUS.md is missing '{heading}'"
