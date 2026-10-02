"""Repository scan for secrets, credentials and personal data.

This exists because the brief asks for a demonstrable, repeatable check rather
than a promise. It walks every tracked file and fails on:

* private keys and their headers;
* cloud and package-registry token shapes;
* assignments that look like secrets (``api_key = "..."``) with a value that
  is not obviously a placeholder;
* e-mail addresses other than the reserved ``.invalid`` ones used as contact
  placeholders;
* credentials in the upstream target URL;
* anything that looks like OPDS or membership credentials for the target site.

    make scan
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Directories that are never scanned.
SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}

#: Files whose whole point is to contain the patterns we look for.
SKIP_FILES = {"scripts/secret_scan.py", "docs/TEST_RESULTS.md"}

#: Only these extensions are worth reading as text.
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".json",
    ".yaml",
    ".yml",
    ".env",
    ".example",
    ".html",
    ".gitignore",
    "",
}

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


@dataclass(frozen=True, slots=True)
class Rule:
    """One pattern to look for, and what to call it if it shows up."""

    name: str
    pattern: re.Pattern[str]
    allow: tuple[str, ...] = ()


#: Every rule. ``allow`` holds substrings that make a hit acceptable.
RULES: tuple[Rule, ...] = (
    Rule("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    Rule(
        "AWS access key id",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    Rule(
        "GitHub token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    ),
    Rule(
        "Slack token",
        re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    ),
    Rule(
        "PyPI token",
        re.compile(r"\bpypi-[A-Za-z0-9_-]{16,}\b"),
    ),
    Rule(
        "generic secret assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|client[_-]?secret)\b"
            r"\s*[:=]\s*[\"'][^\"'\n]{8,}[\"']"
        ),
        allow=(
            "example",
            "invalid",
            "placeholder",
            "changeme",
            "your-",
            "not-a-real",
            "no-credentials",
            "member",
        ),
    ),
    Rule(
        "credential in a URL",
        re.compile(r"https?://[^/\s:@]+:[^/\s:@]+@"),
    ),
    Rule(
        "opds membership credential",
        re.compile(r"(?i)(?:username|password)\s*[:=]\s*\S+.*opds"),
    ),
    Rule(
        "personal e-mail address",
        re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
        allow=("example.invalid", "example.com", "email.invalid", "noreply.invalid"),
    ),
)


def tracked_files() -> list[Path]:
    """Every file git knows about, so nothing untracked or ignored is scanned."""
    try:
        output = subprocess.run(
            ["git", "-C", str(REPO), "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return [
            path
            for path in REPO.rglob("*")
            if path.is_file()
            and not any(part in SKIP_DIRS for part in path.relative_to(REPO).parts)
        ]
    paths = [REPO / line for line in output.splitlines() if line.strip()]
    # Fixtures are generated locally and are deliberately not committed.
    return [path for path in paths if path.exists() and "tests/fixtures" not in str(path)]


def scan_text(name: str, text: str) -> list[str]:
    """Return one finding per rule that matches ``text``."""
    findings = []
    for rule in RULES:
        for match in rule.pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            snippet = match.group(0).strip().replace("\n", " ")
            if any(allowed in snippet for allowed in rule.allow):
                continue
            findings.append(f"{name}:{line}: {rule.name}: {snippet[:80]}")
    return findings


def main() -> int:
    """Scan the repository and report every finding."""
    files = tracked_files()
    findings: list[str] = []
    scanned = 0

    for path in files:
        relative = path.relative_to(REPO).as_posix()
        if relative in SKIP_FILES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        findings.extend(scan_text(relative, text))

    print(f"scanned {scanned} of {len(files)} tracked files against {len(RULES)} rules")
    if findings:
        print(f"\n{RED}{len(findings)} finding(s):{RESET}")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print(f"{GREEN}no secrets, credentials or personal e-mail addresses found{RESET}")
    print("rules checked: " + ", ".join(rule.name for rule in RULES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
