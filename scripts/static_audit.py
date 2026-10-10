#!/usr/bin/env python3
"""Static audit — jc-smart-brain. Prints PASS/FAIL summary; exit 1 on any error."""
import ast, json, os, re, sys
from pathlib import Path

os.chdir("/Users/jarvis/workspace/jc-smart-brain")
errors = []

py_files = sorted(Path("src").rglob("*.py")) + sorted(Path("tests").rglob("*.py"))
for f in py_files:
    text = f.read_text()
    try:
        ast.parse(text)
    except SyntaxError as e:
        errors.append(f"SYNTAX {f}:{e.lineno}: {e.msg}")
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s == "except:":
            errors.append(f"BARE-EXCEPT {f}:{i}")
        for m in ("TODO", "FIXME", "HACK", "XXX"):
            if m in line:
                errors.append(f"MARKER {f}:{i}: {m}")
    if re.search(r"d8c03rr6|sk-proj-[A-Za-z0-9]{20,}", text):
        errors.append(f"SECRET {f}")

kb = Path("src/brain/kb/faq_entries.json")
data = json.loads(kb.read_text())
total = 0
for g, entries in data.items():
    for k, e in entries.items():
        total += 1
        if not isinstance(e, dict) or not e.get("answer"):
            errors.append(f"KB {kb}: {g}/{k} missing answer")

r = Path("render.yaml").read_text()
if "uvicorn" not in r or "/health" not in r or "requirements.txt" not in r:
    errors.append("render.yaml incomplete")
if not os.access("deploy.sh", os.X_OK):
    errors.append("deploy.sh not executable")

print(f"py files: {len(py_files)} | KB entries: {total} in {len(data)} groups")
if errors:
    print(f"ERRORS: {len(errors)}")
    for e in errors:
        print("  ❌", e)
    sys.exit(1)
print("ERRORS: 0 — static audit CLEAN")
