# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C10 — Email Regex Extraction snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Found 3 emails: ['alice@example.com', 'bob@test.org', 'carol@domain.co.uk']",
    "code": '''\
import re

# Simplified RFC 5322 pattern — covers the vast majority of real addresses
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}",
    re.ASCII,
)


def extract_emails(text: str) -> list[str]:
    """Extract and return all unique email addresses from *text*.

    Args:
        text: Input string to scan.

    Returns:
        Sorted list of unique email addresses found, lowercase-normalised.
    """
    if not text:
        return []
    matches = _EMAIL_RE.findall(text)
    return sorted({m.lower() for m in matches})
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "Found 3 emails.",
    "code": '''\
import re

def find_emails(text):
    # Overly loose pattern: matches things like "a@b.c" (1-char TLD)
    pattern = r"[\\w.+\\-]+@[\\w.]+\\.[a-z]+"
    return re.findall(pattern, text, re.IGNORECASE)
''',
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "",
    "code": '''\
def extract_emails(text):
    # BAD: split-based heuristic — misses many valid formats, produces false positives
    words = text.split()
    emails = []
    for word in words:
        if "@" in word:
            emails.append(word.strip(".,;:!?"))
    # BUG: duplicates not removed
    return emails
''',
}
