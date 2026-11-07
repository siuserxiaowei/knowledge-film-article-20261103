"""Behavioral tests for isolated creation and stale-output rejection; no model calls."""
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


new_film = module("new_film")
verifier = module("verify_render")
packager = module("package_skill")


class SkillHelpersTest(unittest.TestCase):
    def test_existing_project_is_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "user-work.txt"
            marker.write_text("keep my work")
            with self.assertRaisesRegex(ValueError, "not empty"):
                new_film.create_project(temp)
            self.assertEqual(marker.read_text(), "keep my work")
            self.assertEqual(list(Path(temp).iterdir()), [marker])

    def test_prevents_recursive_creation_in_skill(self):
        with self.assertRaisesRegex(ValueError, "outside the installed"):
            new_film.create_project(new_film.SKILL / "accidental-output")

    def test_new_project_has_its_own_script_and_not_fake_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            new_film.create_project(root, "attention")
            spec = json.loads((root / "content/film.json").read_text())
            timeline = json.loads((root / "src/generated/timeline.json").read_text())
            self.assertIn("budget", [s["kind"] for s in spec["scenes"]])
            self.assertFalse(timeline["ready"])
            self.assertFalse(timeline["narrated"])
            self.assertTrue((root / "tools/prepare_film.py").is_file())
            self.assertFalse((root / "node_modules").exists())
            self.assertFalse((root / ".env").exists())

    def test_stale_timeline_cannot_produce_successful_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            new_film.create_project(root)
            (root / "out").mkdir()
            (root / "out/film.mp4").write_bytes(b"not a valid video")
            with patch.object(verifier.shutil, "which", return_value="available"), \
                 patch.object(verifier, "execute", side_effect=AssertionError("must reject before probing")):
                report = verifier.verify(root, Path("out/film.mp4"), 0)
            self.assertEqual(report["status"], "failed")
            self.assertIn("not ready", report["error"])
            self.assertEqual(report["humanReview"]["visual"], "pending")

    def test_package_is_reproducible_and_excludes_private_runtime_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "demo-skill"
            root.mkdir()
            (root / "SKILL.md").write_text("skill")
            (root / "VERSION").write_text("1.1.0")
            for relative in (".env", ".env.local", "node_modules/a.js", "tools/__pycache__/x.pyc", "reviews/private.json"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("private runtime data")
            (root / ".env.example").write_text("KEY=")
            one = packager.package(root, Path(temp) / "one.zip")
            two = packager.package(root, Path(temp) / "two.zip")
            self.assertEqual(one["sha256"], two["sha256"])
            with zipfile.ZipFile(one["archive"]) as archive:
                names = archive.namelist()
                self.assertEqual(set(names), {"demo-skill/SKILL.md", "demo-skill/VERSION", "demo-skill/.env.example", "demo-skill/RELEASE.json"})
                release = json.loads(archive.read("demo-skill/RELEASE.json"))
                self.assertEqual(release["version"], "1.1.0")

    def test_package_rejects_symlinks_and_output_inside_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "demo-skill"
            root.mkdir()
            (root / "SKILL.md").write_text("skill")
            (root / "VERSION").write_text("1.1.0")
            (root / "linked").symlink_to(Path(temp) / "elsewhere")
            with self.assertRaisesRegex(ValueError, "symlink"):
                packager.package(root, Path(temp) / "one.zip")
            with self.assertRaisesRegex(ValueError, "outside"):
                packager.package(root, root / "one.zip")

    def test_verification_cannot_reuse_ready_when_current_source_guard_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            new_film.create_project(root)
            spec = json.loads((root / "content/film.json").read_text())
            digest = hashlib.sha256(json.dumps(verifier.canonical(spec), ensure_ascii=False,
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            timeline = root / "src/generated/timeline.json"
            data = json.loads(timeline.read_text())
            data.update(ready=True, specHash=digest)
            timeline.write_text(json.dumps(data))
            (root / "out").mkdir()
            (root / "out/film.mp4").write_bytes(b"old encoded output")
            with patch.object(verifier.shutil, "which", return_value="available"), \
                 patch.object(verifier, "execute", side_effect=RuntimeError("Imported source changed")) as execution:
                report = verifier.verify(root, Path("out/film.mp4"), 0)
            self.assertEqual(report["status"], "failed")
            self.assertIn("Imported source changed", report["error"])
            self.assertEqual(execution.call_count, 1)
            self.assertEqual(Path(execution.call_args.args[0][1]).name, "check-film.mjs")
            self.assertEqual(report["humanReview"]["visual"], "pending")


if __name__ == "__main__":
    unittest.main()
