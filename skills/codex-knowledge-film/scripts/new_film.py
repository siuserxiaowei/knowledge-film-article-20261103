#!/usr/bin/env python3
"""Create an isolated knowledge-film project; never overwrite existing work."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

SKILL = Path(__file__).resolve().parent.parent


def ignore_files(directory, names):
    return [name for name in names if name in {
        "node_modules", ".git", ".venv", ".cache", "__pycache__", "out", "reviews", ".env"
    } or name.startswith(".venv-") or name.endswith((".pyc", ".pending.json"))
        or (name.startswith(".env.") and name != ".env.example")]


def create_project(output, example="queue", title=None):
    output = Path(output).expanduser().resolve()
    if output == Path(output.anchor) or output == Path.home().resolve():
        raise ValueError("Choose a new project folder, not a filesystem or home directory")
    if output == SKILL or SKILL in output.parents or output in SKILL.parents:
        raise ValueError("Create the project outside the installed Skill directory")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output directory is not empty; existing work was left untouched")
    source = SKILL / "assets/template"
    example_file = source / "examples" / f"{example}.json"
    if example not in ("queue", "attention") or not example_file.is_file():
        raise ValueError("Choose an available example: queue or attention")
    spec = json.loads(example_file.read_text(encoding="utf-8"))
    if title:
        spec["title"] = title
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, output, dirs_exist_ok=True, ignore=ignore_files)
    (output / "content").mkdir(exist_ok=True)
    (output / "content/film.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generated = output / "src/generated/timeline.json"
    generated.parent.mkdir(parents=True, exist_ok=True)
    stub = {"version": 1, "ready": False, "title": spec["title"], "fps": spec["fps"],
            "width": spec["width"], "height": spec["height"], "durationSeconds": 1,
            "durationInFrames": spec["fps"], "specHash": "", "audioSrc": None,
            "narrated": False, "provenance": {"status": "not-prepared"},
            "theme": spec.get("theme", {}), "scenes": [], "captions": []}
    generated.write_text(json.dumps(stub, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    storyboard = [f"# {spec['title']} · 示例分镜", "", "本示例为机制演示；新题目需重写文稿、事实来源和专用场景。", "",
                  "|场景|画法|口语/字幕|", "|---|---|---|"]
    for scene in spec["scenes"]:
        lines = "；".join(line["text"] for line in scene.get("lines", [])) or scene["title"]
        storyboard.append(f"|{scene['id']}|{scene['kind']}|{lines.replace('|', '／')}|")
    (output / "content/storyboard.md").write_text("\n".join(storyboard) + "\n", encoding="utf-8")
    (output / "content/facts.md").write_text(
        f"# {spec['title']} · 事实与来源\n\n本示例的数字和变化为机制示意，不是研究实测结论。\n"
        "制作新题目时在这里记录：一句话论点、实际引用的资料链接、事实与示意区别、文稿改写和不确定点。\n",
        encoding="utf-8")
    (output / "AGENTS.md").write_text(
        "# Knowledge Film\n\n"
        "- Read content/facts.md and content/storyboard.md before changing the story.\n"
        "- content/film.json is the source. Generate src/generated/timeline.json with python3 tools/prepare_film.py.\n"
        "- Keep all model calls outside React, Studio and frame rendering. Cache real audio before rendering.\n"
        "- Do not label silent or imported audio as verified Ming speech. Never commit credentials.\n"
        "- Use frame/fps for deterministic animation and load fonts before capture.\n"
        "- npm run check validates the current timeline; npm run render exports KnowledgeFilm.\n"
        "- Inspect encoded frames and actual soundtrack; technical checks do not verify their meaning.\n",
        encoding="utf-8")
    for name in ("LICENSE", "SOURCES.md"):
        if (SKILL / name).is_file():
            content = (SKILL / name).read_text(encoding="utf-8")
            if name == "SOURCES.md":
                content = content.replace("assets/template/public/fonts", "public/fonts")
            (output / name).write_text(content, encoding="utf-8")
    return {"project": str(output), "example": example, "title": spec["title"],
            "status": "created-not-prepared", "modelRequests": 0,
            "next": ["npm ci", "python3 tools/prepare_film.py --mode silent", "npm run check", "npm run studio"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--example", choices=("queue", "attention"), default="queue")
    parser.add_argument("--title", help="Change the title only; does not rewrite narration or scene design")
    args = parser.parse_args()
    try:
        print(json.dumps(create_project(args.output, args.example, args.title), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print("Project creation stopped: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
