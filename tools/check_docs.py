#!/usr/bin/env python3
"""Structural checks for the repository's Markdown.

Checks
  1. Every hub/*/L*.md has exactly the eleven required H2 headings, in order, and a Level line.
  2. Every relative Markdown link resolves to an existing file (anchors are ignored).
  3. Non-inclusive terms are absent (allowlisted lines may carry `<!-- term-ok -->`).
  4. No 12-digit account IDs other than 123456789012 / 000000000000.
  5. Every YAML/JSON file parses (YAML may contain several documents).

Exit code 1 when any check fails. Run from the repository root.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_H2 = [
    "## 1. Mental model",
    "## 2. Concepts",
    "## 3. How it interacts with the rest of AWS",
    "## 4. Use it when / avoid it when",
    "## 5. Well-Architected view",
    "## 6. Failure modes and troubleshooting",
    "## 7. Signals: metrics, logs, traces",
    "## 8. Testing and DR notes",
    "## 9. Hands-on",
    "## 10. Check yourself",
    "## 11. Sources",
]

NON_INCLUSIVE = re.compile(r"\b(master|slave|whitelist|blacklist|whiteday|blackday)s?\b", re.I)  # term-ok
ACCOUNT_ID = re.compile(r"(?<![0-9a-fA-F.])\d{12}(?![0-9a-fA-F.])")  # skip digit runs inside hex (SHAs, digests)
ALLOWED_IDS = {"123456789012", "000000000000"}
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_DIRS = {".git", "node_modules", ".venv", "dist", "__pycache__", ".pytest_cache"}


def iter_files(suffixes: tuple[str, ...]):
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in suffixes:
            yield path


def check_headings(errors: list[str]) -> None:
    for path in sorted((ROOT / "hub").glob("*/L*.md")):
        text = strip_code_blocks(path.read_text(encoding="utf-8"))
        h2s = [line.rstrip() for line in text.splitlines() if line.startswith("## ")]
        if h2s != REQUIRED_H2:
            missing = [h for h in REQUIRED_H2 if h not in h2s]
            extra = [h for h in h2s if h not in REQUIRED_H2]
            order = "order differs" if not missing and not extra else ""
            errors.append(
                f"{path.relative_to(ROOT)}: H2 structure invalid "
                f"(missing={missing} extra={extra} {order})".strip()
            )
        h1s = [line for line in text.splitlines() if line.startswith("# ")]
        if len(h1s) != 1:
            errors.append(f"{path.relative_to(ROOT)}: expected exactly one H1, found {len(h1s)}")
        if "**Level:**" not in text:
            errors.append(f"{path.relative_to(ROOT)}: missing '**Level:**' line")


def strip_code_blocks(text: str) -> str:
    out, fenced = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return "\n".join(out)


def check_links(errors: list[str]) -> None:
    for path in iter_files((".md",)):
        text = strip_code_blocks(path.read_text(encoding="utf-8"))
        for match in LINK.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"{path.relative_to(ROOT)}: broken link -> {match.group(1)}")


def check_language(errors: list[str]) -> None:
    for path in iter_files((".md", ".yaml", ".yml", ".json", ".sh", ".ts", ".go", ".py", ".toml", "")):
        if path.suffix == "" and path.name not in {"Dockerfile", "Makefile", "Jenkinsfile"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            if "term-ok" in line:
                continue
            if NON_INCLUSIVE.search(line):
                errors.append(f"{path.relative_to(ROOT)}:{number}: non-inclusive term: {line.strip()[:100]}")
            for match in ACCOUNT_ID.finditer(line):
                if match.group(0) not in ALLOWED_IDS:
                    errors.append(f"{path.relative_to(ROOT)}:{number}: unexpected 12-digit id {match.group(0)}")


def check_yaml_json(errors: list[str]) -> None:
    try:
        import yaml  # type: ignore
    except ImportError:  # pragma: no cover
        errors.append("PyYAML not installed: run tools/check.sh which uses .venv")
        return

    class Loader(yaml.SafeLoader):
        pass

    def unknown(loader, tag_suffix, node):  # CloudFormation intrinsics such as !Ref, !Sub
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    Loader.add_multi_constructor("!", unknown)

    for path in iter_files((".yaml", ".yml")):
        if "templates" in path.parts and "helm" in str(path).lower():
            continue  # Helm templates are not YAML until rendered
        try:
            list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=Loader))
        except yaml.YAMLError as exc:
            errors.append(f"{path.relative_to(ROOT)}: YAML parse error: {str(exc).splitlines()[0]}")
    for path in iter_files((".json",)):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.relative_to(ROOT)}: JSON parse error: {exc}")


def main() -> int:
    errors: list[str] = []
    check_headings(errors)
    check_links(errors)
    check_language(errors)
    check_yaml_json(errors)
    docs = len(list((ROOT / "hub").glob("*/L*.md")))
    if errors:
        print("\n".join(errors))
        print(f"\n{len(errors)} problem(s) found across {docs} leveled documents.")
        return 1
    print(f"OK: {docs} leveled documents, links, language, YAML/JSON all pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
