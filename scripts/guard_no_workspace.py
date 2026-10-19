"""LIC-10 guard: no campaign workspace and no Source may enter the tool repository.

Checks the paths given as arguments, or every file tracked by git when there are none.
The sample campaign's folder is exempt (a Golarion deny-list scan covers it instead).
Exits 1 and names each offending path.
"""

import subprocess
import sys
from pathlib import PurePosixPath

SAMPLE_CAMPAIGN = "sample-campaign"
# ponytail: Sources recognised by extension or file name; extend as new Source kinds appear.
SOURCE_SUFFIXES = {".flac", ".wav", ".mp3", ".ogg", ".opus", ".m4a", ".webm", ".pdf"}
SOURCE_NAMES = {"world.json"}  # a Foundry world


def offences(paths: list[str]) -> list[str]:
    found = []
    for raw in paths:
        path = PurePosixPath(raw)
        if path.parts[:1] == (SAMPLE_CAMPAIGN,):
            continue
        if path.name == "workspace.yaml" or ".secondchair" in path.parts[:-1]:
            found.append(f"{raw}: campaign workspace file")
        elif path.suffix.lower() in SOURCE_SUFFIXES or path.name in SOURCE_NAMES:
            found.append(f"{raw}: looks like a Source")
    return found


def main(argv: list[str]) -> int:
    paths = (
        argv
        or subprocess.run(
            ["git", "ls-files"], check=True, capture_output=True, text=True
        ).stdout.splitlines()
    )
    found = offences(paths)
    for line in found:
        print(f"LIC-10: {line}; campaign workspaces and Sources stay out of the repository.")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
