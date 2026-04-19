#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
"""Audit dependency licenses for Engramia releases.

Inspects the currently active Python environment and regenerates
docs/legal/DEPENDENCY_LICENSES.md. The caller controls what is
installed — this script does not touch the venv.

Expected release flow (see .github/workflows/prepare-release.yml):

    python -m venv .audit-venv
    . .audit-venv/bin/activate       # `Scripts\\activate` on Windows
    pip install ".[all]"             # runtime extras only — no [dev]
    pip install pip-licenses
    python scripts/audit_licenses.py

Modes:
    (default)          Regenerate docs/legal/DEPENDENCY_LICENSES.md.
    --check            Exit 1 if the generated output would differ
                       from the committed file. Used on every PR to
                       catch drift after a dependency change.
    --stdout           Write generated markdown to stdout (no file).
    --fail-on=high     Exit 2 if any HIGH-risk license is present
                       (default). Use `--fail-on=none` to disable.

Risk tiers vs BUSL 1.1 commercial release:
    HIGH     AGPL / GPL-3.0 / SSPL        blocks release
    MEDIUM   LGPL family                  Python import is dynamic
                                          linking; copyleft does not
                                          propagate. Safe to ship.
    LOW      MPL-2.0                      file-level copyleft; safe
                                          if files are unmodified.
    OK       MIT / BSD / Apache / ISC /
             PSF / Unlicense / 0BSD /
             CC0 / Zlib / ...             permissive.
    UNKNOWN  metadata missing             verify manually.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

SELF_PACKAGE = "engramia"

# Order matters — first match wins. LGPL must match before GPL, because
# "Lesser GPL" contains the token "GPL".
_MEDIUM_PATTERNS = [
    r"\bLGPL",
    r"Lesser General",
    r"Library or Lesser",
]
_HIGH_PATTERNS = [
    r"\bAGPL",
    r"Affero",
    r"\bGPL-?3",
    r"\bGPLv3",
    r"GNU General Public License v3",
    r"\bSSPL",
    r"Server Side Public License",
    r"Commons Clause",
]
_LOW_PATTERNS = [
    r"\bMPL\b",
    r"Mozilla Public",
]
_OK_PATTERNS = [
    r"\bMIT\b",
    r"\bBSD\b",
    r"\bApache\b",
    r"\bISC\b",
    r"\bPSF\b",
    r"Python Software Foundation",
    r"Unlicense",
    r"\b0BSD\b",
    r"\bZlib\b",
    r"\bCC0",
    r"\bUPL\b",
    r"\bBlueOak",
    r"\bPublic Domain\b",
]

RISK_EMOJI = {
    "HIGH": "🔴",
    "MEDIUM": "🟡",
    "LOW": "🟠",
    "OK": "✅",
    "UNKNOWN": "⚠️",
}
RISK_LABELS = {
    "HIGH": "🔴 HIGH",
    "MEDIUM": "🟡 MEDIUM",
    "LOW": "🟠 LOW",
    "OK": "✅ OK",
    "UNKNOWN": "⚠️ UNKNOWN",
}
RISK_NOTES = {
    "HIGH": (
        "Strong copyleft — incompatible with BUSL 1.1 commercial "
        "distribution. Must be removed or replaced before release."
    ),
    "MEDIUM": (
        "LGPL — Python import model is dynamic linking, copyleft does "
        "not propagate. Unmodified commercial use is safe. Widely used "
        "in commercial products."
    ),
    "LOW": (
        "MPL-2.0 — file-level copyleft only. Unmodified commercial use is safe; only modified MPL files must be shared."
    ),
    "UNKNOWN": ("License metadata missing or unrecognized. Verify manually before release."),
}

RISK_ORDER = ["HIGH", "MEDIUM", "LOW", "UNKNOWN", "OK"]

# Platform-suffix pattern on package names — collapses variants like
# `nvidia-cudnn-cu12`, `@foo/bar-linux-x64`, or hypothetical future
# platform-specific Python wheels into a single canonical entry so the
# committed inventory is stable across macOS / Linux / Alpine / Windows
# regenerations. Python packages currently rarely use this naming, but
# the normalizer is kept in sync with the Node-side audit script.
_PLATFORM_SUFFIX_RE = re.compile(
    r"-(linux|linuxmusl|darwin|win32|freebsd|android|sunos|netbsd|openbsd|manylinux|musllinux)"
    r"-(x64|arm64|arm|ia32|x86_64|aarch64|ppc64|ppc64le|s390x|mips|mipsel|riscv64)"
    r"(-(gnu|musl|msvc|eabi|eabihf))?$",
    re.IGNORECASE,
)


def _canonical_name(name: str) -> str:
    return _PLATFORM_SUFFIX_RE.sub("-<platform>", name)


@dataclass
class Package:
    name: str
    version: str
    license: str
    risk: str


def classify(license_str: str) -> str:
    text = license_str or ""
    # Medium first so "Lesser GPL" doesn't get caught by HIGH's GPL rule.
    for p in _MEDIUM_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return "MEDIUM"
    for p in _HIGH_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return "HIGH"
    for p in _LOW_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return "LOW"
    for p in _OK_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return "OK"
    return "UNKNOWN"


def run_pip_licenses() -> list[Package]:
    # Prefer module invocation (portable across venvs); fall back to entry point.
    for cmd in (
        [sys.executable, "-m", "piplicenses", "--format=json"],
        ["pip-licenses", "--format=json"],
    ):
        try:
            raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            break
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    else:
        print(
            "::error::pip-licenses not found. Install with `pip install pip-licenses`.",
            file=sys.stderr,
        )
        sys.exit(3)

    data = json.loads(raw)
    # Collapse platform-specific variants (if any) into a single canonical
    # entry. Only entries whose name actually carries a platform suffix
    # are collapsed — versioned duplicates of the same package must be
    # preserved as separate rows.
    canonical: dict[str, Package] = {}
    rest: list[Package] = []
    for item in data:
        raw_name = item["Name"]
        if raw_name.lower() == SELF_PACKAGE:
            continue
        name = _canonical_name(raw_name)
        lic = (item.get("License") or "UNKNOWN").strip()
        pkg = Package(
            name=name,
            version=(item.get("Version") or "").strip(),
            license=lic,
            risk=classify(lic),
        )
        if name == raw_name:
            rest.append(pkg)
            continue
        existing = canonical.get(name)
        if existing is None or RISK_ORDER.index(pkg.risk) < RISK_ORDER.index(existing.risk):
            canonical[name] = pkg
    out = rest + list(canonical.values())
    out.sort(key=lambda p: p.name.lower())
    return out


def _engramia_version() -> str:
    try:
        return metadata.version(SELF_PACKAGE)
    except metadata.PackageNotFoundError:
        return "unknown"


def render_markdown(packages: list[Package], version: str, today: dt.date) -> str:
    counts = {r: 0 for r in RISK_ORDER}
    for p in packages:
        counts[p.risk] = counts.get(p.risk, 0) + 1
    flagged = [p for p in packages if p.risk != "OK"]

    buf: list[str] = []
    buf.append("# Dependency License Inventory — Engramia (Core)")
    buf.append("")
    buf.append(f"Generated: {today.isoformat()}  |  Engramia version: {version}")
    buf.append("")
    buf.append(
        "Runtime Python dependencies that ship with the `engramia` wheel "
        "and Docker image. Auto-generated by "
        "[`scripts/audit_licenses.py`](../../scripts/audit_licenses.py) "
        'against a fresh venv installed with `pip install ".[all]"` '
        "(runtime extras only — no dev, docs, or test tooling). Do not "
        "edit manually; CI will reject drift."
    )
    buf.append("")
    buf.append(
        "Frontend dependencies (Next.js admin dashboard) ship in a "
        "separate Docker image and are audited in the Dashboard repo: "
        "[engramia/dashboard → docs/legal/DEPENDENCY_LICENSES.md]"
        "(https://github.com/engramia/dashboard/blob/main/docs/legal/DEPENDENCY_LICENSES.md)."
    )
    buf.append("")

    buf.append("## Summary")
    buf.append("")
    buf.append("| | Count |")
    buf.append("|---|---|")
    buf.append(f"| Python packages (runtime transitive closure) | {len(packages)} |")
    buf.append(f"| 🔴 HIGH — must resolve before release | {counts['HIGH']} |")
    buf.append(f"| 🟡 MEDIUM — review required | {counts['MEDIUM']} |")
    buf.append(f"| 🟠 LOW — safe, note only | {counts['LOW']} |")
    buf.append(f"| ⚠️ UNKNOWN — verify manually | {counts['UNKNOWN']} |")
    buf.append(f"| ✅ OK | {counts['OK']} |")
    buf.append("")
    if counts["HIGH"] == 0 and counts["UNKNOWN"] == 0:
        buf.append(
            "**Result: no blocking issues. All flagged packages are "
            "safe for commercial distribution under BUSL 1.1 (see "
            "notes below).**"
        )
    elif counts["HIGH"] == 0:
        buf.append(
            f"**Result: no blocking issues. {counts['UNKNOWN']} "
            "package(s) have unrecognized license metadata and need "
            "manual review.**"
        )
    else:
        buf.append(
            f"**Result: {counts['HIGH']} HIGH-risk package(s) detected. "
            "Release is BLOCKED until these are removed or replaced.**"
        )
    buf.append("")

    if flagged:
        buf.append("## Flagged packages")
        buf.append("")
        buf.append("| Risk | Package | Version | License | Assessment |")
        buf.append("|---|---|---|---|---|")
        for p in sorted(
            flagged,
            key=lambda x: (RISK_ORDER.index(x.risk), x.name.lower()),
        ):
            note = RISK_NOTES.get(p.risk, "")
            buf.append(f"| {RISK_LABELS[p.risk]} | {p.name} | {p.version} | {p.license} | {note} |")
        buf.append("")

    buf.append("## Full list")
    buf.append("")
    buf.append("| Package | Version | License | Risk |")
    buf.append("|---|---|---|---|")
    for p in packages:
        buf.append(f"| {p.name} | {p.version} | {p.license} | {RISK_EMOJI[p.risk]} |")
    buf.append("")

    buf.append("## Update process")
    buf.append("")
    buf.append(
        "- **Release time** — `prepare-release.yml` installs the runtime "
        "extras into a clean venv and runs this script; the refreshed "
        "file is committed alongside the new LICENSE.txt before the "
        "release tag is pushed."
    )
    buf.append(
        "- **Pull requests** — `ci.yml` runs "
        "`python scripts/audit_licenses.py --check` to fail if this file "
        "is stale after a dependency change."
    )
    buf.append(
        '- **Manual refresh** — `pip install ".[all]" pip-licenses` in '
        "a clean venv, then `python scripts/audit_licenses.py`."
    )
    buf.append("")
    buf.append("---")
    buf.append("")
    buf.append("*Auto-generated. Do not edit manually.*")
    buf.append("")
    return "\n".join(buf)


def _normalize_for_check(text: str) -> str:
    # Drop the Generated/version header line before comparing — it is the
    # only thing that varies between identical dependency trees (date +
    # hatch-vcs dev suffix on PR branches).
    return re.sub(
        r"^Generated: [^|]*\|\s*Engramia version: .*$",
        "Generated: <date>  |  Engramia version: <version>",
        text,
        flags=re.MULTILINE,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate docs/legal/DEPENDENCY_LICENSES.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output",
        default="docs/legal/DEPENDENCY_LICENSES.md",
        help="Path to the file to generate (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if generated output would differ from --output",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write generated markdown to stdout (no file write)",
    )
    parser.add_argument(
        "--fail-on",
        choices=["high", "unknown", "none"],
        default="high",
        help="Risk tier that forces exit code 2 (default: high)",
    )
    args = parser.parse_args(argv)

    packages = run_pip_licenses()
    version = _engramia_version()
    today = dt.datetime.now(dt.UTC).date()
    generated = render_markdown(packages, version, today)

    high = sum(1 for p in packages if p.risk == "HIGH")
    unknown = sum(1 for p in packages if p.risk == "UNKNOWN")

    if args.stdout:
        # Force UTF-8 on stdout — default cp1250 on Windows can't encode emoji.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(generated)
    elif args.check:
        out_path = Path(args.output)
        if not out_path.exists():
            print(
                f"::error::{out_path} does not exist. Run `python scripts/audit_licenses.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        existing = out_path.read_text(encoding="utf-8")
        if _normalize_for_check(existing) != _normalize_for_check(generated):
            print(
                f"::error::{out_path} is stale. A dependency change "
                "was made without regenerating the audit. Run "
                "`python scripts/audit_licenses.py` locally and commit "
                "the result.",
                file=sys.stderr,
            )
            return 1
        print(f"{out_path} is up to date ({len(packages)} packages).")
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(generated, encoding="utf-8")
        print(f"{out_path} regenerated — {len(packages)} packages.")

    if args.fail_on == "high" and high > 0:
        print(
            f"::error::{high} HIGH-risk license(s) present — release blocked.",
            file=sys.stderr,
        )
        return 2
    if args.fail_on == "unknown" and (high > 0 or unknown > 0):
        print(
            f"::error::{high} HIGH, {unknown} UNKNOWN license(s) — release blocked.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
