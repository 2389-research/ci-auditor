#!/bin/sh
# ABOUTME: Canonical check for the ci-timing-audit skill: script tests plus SKILL.md rules.
# ABOUTME: Run it after any change to SKILL.md or scripts/: sh tests/check.sh
set -eu
cd "$(dirname "$0")/.."

echo "== script tests"
python3 -m unittest discover -s tests

echo "== SKILL.md"
python3 - <<'EOF'
import re, sys
text = open("SKILL.md").read()
m = re.match(r"---\n(.*?)\n---\n", text, re.S)
problems = []
if not m:
    sys.exit("FAIL: SKILL.md has no frontmatter block")
front = m.group(1)
name = re.search(r'^name: "?([^"\n]+)"?$', front, re.M)
desc = re.search(r'^description: "?(.+?)"?$', front, re.M)
if not name or not re.fullmatch(r"[a-z0-9-]+", name.group(1)):
    problems.append("name must use only lowercase letters, digits and hyphens")
if not desc or not desc.group(1).startswith("Use when"):
    problems.append('description must start with "Use when"')
if len(front) > 1024:
    problems.append(f"frontmatter is {len(front)} characters; the limit is 1024")
if "evals/" in text:
    problems.append("SKILL.md must not mention evals/ (agents read the scenarios mid-task)")
if "scripts/ci_timing.py" not in text:
    problems.append("SKILL.md must point at scripts/ci_timing.py")
for p in problems:
    print("FAIL:", p)
sys.exit(1 if problems else 0)
EOF
echo "ok"
