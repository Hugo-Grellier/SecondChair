"""ARC-01: the Core imports no System extension, VTT connector or Surface package.

The Core may import the standard library, its own modules and the third-party libraries listed
in `CORE_THIRD_PARTY`; anything else, any other `secondchair` package included, fails.
"""

import ast
import sys
from pathlib import Path

CORE = Path(__file__).parent.parent / "src" / "secondchair" / "core"
CORE_THIRD_PARTY = {"mcp", "numpy", "starlette", "uvicorn", "yaml"}


def foreign_imports(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 1:  # relative import climbing out of the Core
                found.append("." * node.level + (node.module or ""))
                continue
            names = [] if node.level else [node.module or ""]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top == "secondchair":
                if not (name == "secondchair.core" or name.startswith("secondchair.core.")):
                    found.append(name)
            elif top not in sys.stdlib_module_names and top not in CORE_THIRD_PARTY:
                found.append(name)
    return found


def test_the_core_imports_only_itself_stdlib_and_its_libraries() -> None:
    offences = {
        str(path.relative_to(CORE)): bad
        for path in CORE.rglob("*.py")
        if (bad := foreign_imports(path.read_text()))
    }
    assert offences == {}


def test_the_check_catches_surface_extension_and_connector_imports() -> None:
    source = (
        "import secondchair.cli\n"
        "from secondchair import pf2e\n"
        "from secondchair_foundry import bridge\n"
        "from .. import cli\n"
        "from secondchair.core import tools\n"
        "import json\n"
    )
    assert foreign_imports(source) == [
        "secondchair.cli",
        "secondchair",
        "secondchair_foundry",
        "..",
    ]
