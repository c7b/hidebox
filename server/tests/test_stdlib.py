# SPDX-License-Identifier: MIT
"""S-01: only standard-library imports anywhere in server/, and an SPDX line at the top of every source file.

Run on Python 3.13 (the server), sys.stdlib_module_names also rejects any module that only 3.14 has.
"""
import ast
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
OURS = {"mutis", "harness", "make_vectors"} | {p.stem for p in (SERVER / "tests").glob("test_*.py")}


def python_files() -> list[Path]:
    files = [p for p in SERVER.rglob("*.py") if "__pycache__" not in p.parts]
    return files + sorted((SERVER / "bin").iterdir())


class Stdlib(unittest.TestCase):
    def test_imports(self):
        for path in python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                for name in names:
                    self.assertTrue(name in sys.stdlib_module_names or name in OURS, f"{path}: import {name}")

    def test_spdx_headers(self):
        sources = python_files() + list(SERVER.rglob("*.sql")) + list(SERVER.glob("*.md"))
        for path in sources:
            head = path.read_text(encoding="utf-8").splitlines()[:2]
            self.assertTrue(any("SPDX-License-Identifier: MIT" in line for line in head), str(path))


if __name__ == "__main__":
    unittest.main()
