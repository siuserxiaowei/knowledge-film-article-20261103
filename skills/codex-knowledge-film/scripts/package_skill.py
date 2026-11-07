#!/usr/bin/env python3
"""Build a reproducible Skill ZIP with portable per-file checksums and no runtime state."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile

SKILL = Path(__file__).resolve().parent.parent
EXCLUDED = {"node_modules", ".git", ".cache", "__pycache__", ".venv", "out", "reviews"}


def excluded(relative):
    return any(part in EXCLUDED or part.startswith(".venv-") for part in relative.parts) or any(
        part == ".env" or (part.startswith(".env.") and part != ".env.example")
        for part in relative.parts) or relative.name.endswith((".pyc", ".pending", ".pending.json", ".DS_Store"))


def package(skill, output):
    skill, output = Path(skill).resolve(), Path(output).resolve()
    if output == skill or skill in output.parents:
        raise ValueError("Write the ZIP outside the installed Skill")
    if not (skill / "SKILL.md").is_file():
        raise ValueError("SKILL.md is missing")
    version = (skill / "VERSION").read_text(encoding="utf-8").strip()
    files = {}
    for path in sorted(skill.rglob("*")):
        relative = path.relative_to(skill)
        if excluded(relative):
            continue
        if path.is_symlink():
            raise ValueError("Refusing to package a symlink: " + str(relative))
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes()
    manifest = {"version": version, "skill": skill.name, "formatVersion": 1,
                "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()}}
    if "RELEASE.json" in files:
        raise ValueError("RELEASE.json is generated inside the archive; remove a stale local copy")
    files["RELEASE.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_suffix(output.suffix + ".pending")
    with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(skill.name + "/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(pending) as archive:
        if archive.testzip():
            raise ValueError("ZIP integrity check failed")
    pending.replace(output)
    return {"version": version, "files": len(files), "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "archive": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(SKILL, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
