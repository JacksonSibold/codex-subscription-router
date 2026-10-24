"""Dependency-free checks for the publishable source tree."""
from __future__ import annotations

import json
from pathlib import Path
import py_compile
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import settings

for folder in ("router", "scripts", "tests"):
    for source in (ROOT / folder).glob("*.py"):
        py_compile.compile(str(source), doraise=True)
        print(f"PASS Python syntax: {source.relative_to(ROOT)}")

for document in (ROOT / "catalog").glob("*.json"):
    json.loads(document.read_text(encoding="utf-8"))
    print(f"PASS JSON: {document.relative_to(ROOT)}")

for document in (ROOT / "examples").glob("*.toml"):
    tomllib.loads(document.read_text(encoding="utf-8"))
    print(f"PASS TOML: {document.relative_to(ROOT)}")

for document in (ROOT / "examples").glob("router-settings*.json"):
    settings.validate(json.loads(document.read_text(encoding="utf-8")))
    print(f"PASS settings schema: {document.relative_to(ROOT)}")

secret_pattern = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|gho_[A-Za-z0-9]{20,}|oc_sk_[A-Za-z0-9_-]{12,})")
skipped = {".git", "__pycache__", "node_modules", "dist", ".dev-codex", "artifacts", ".venv"}
for document in ROOT.rglob("*"):
    if not document.is_file() or skipped.intersection(document.parts):
        continue
    if document.suffix.lower() not in {".py", ".json", ".toml", ".md", ".gitignore", ".js", ".jsx", ".mjs", ".yml", ".yaml", ".cmd"}:
        continue
    text = document.read_text(encoding="utf-8")
    relative = document.relative_to(ROOT)
    assert "C:\\Users\\" not in text, f"Machine-specific path in {relative}"
    assert not secret_pattern.search(text), f"Possible credential in {relative}"
print("PASS no user-specific paths or detected credentials")
