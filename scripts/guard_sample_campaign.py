"""LIC-10 / LIC-13: scan shipped sample material against the curated setting deny-list.

Usage: python scripts/guard_sample_campaign.py [sample-directory]
Scans all files, including untracked files, so it also works before staging a draft.
"""

import re
import sys
from pathlib import Path

DENY_LIST = Path(__file__).with_name("sample-setting-deny-list.txt")
ROOT = Path(__file__).resolve().parent.parent


def offences(folder: Path) -> list[str]:
    terms = [
        line.strip()
        for line in DENY_LIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, terms)) + r")\b", re.IGNORECASE)
    found = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in pattern.finditer(line):
                found.append(f"{path}:{number}: forbidden setting term {match[0]!r}")
    return found


def main(argv: list[str]) -> int:
    folder = Path(argv[0]) if argv else ROOT / "sample-campaign"
    if not folder.is_dir() or not any(folder.rglob("*")):
        print(f"LIC-13: missing or empty sample campaign: {folder}")
        return 1
    try:
        found = offences(folder)
    except (OSError, UnicodeError) as error:
        print(f"LIC-13: cannot scan sample campaign: {error}")
        return 1
    for line in found:
        print(f"LIC-13: {line}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
