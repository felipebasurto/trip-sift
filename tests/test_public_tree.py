from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG_NS = "{http://www.w3.org/2000/svg}"

IGNORED_AUDIT_DIRS = {
    ".git",
    ".superpowers",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "results",
}

README_SVG_REFS = (
    "docs/assets/viajante-hero.svg",
    "docs/assets/how-viajante-works.svg",
)

BANNED_SUFFIXES = {".csv", ".log"}
ALLOWED_JSON_DIRS = {ROOT / "tests"}


def _banned_path_markers() -> tuple[str, ...]:
    return (
        "Fel" + "ipe",
        "prague_" + "confirmed_stay",
        ".pw_state",
    )


def _home_path_marker() -> str:
    return "/" + "Users" + "/"


def _is_under_ignored_audit_dir(rel: Path) -> bool:
    return any(part in IGNORED_AUDIT_DIRS for part in rel.parts)


def _should_scan_text_content(path: Path) -> bool:
    if path.name == "test_public_tree.py":
        return False
    if path.name == ".gitignore":
        return True
    return path.suffix in {".py", ".md", ".toml", ".svg"}


class PublicTreeHygieneTests(unittest.TestCase):
    def test_generated_results_are_ignored_by_audit(self) -> None:
        self.assertTrue(_is_under_ignored_audit_dir(Path("results/search.viajante.json")))

    def test_no_private_artifacts(self) -> None:
        offenders: list[str] = []
        audited_count = 0
        banned_paths = _banned_path_markers()
        home_marker = _home_path_marker()
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if _is_under_ignored_audit_dir(rel):
                continue
            audited_count += 1
            text = str(rel)
            for fragment in banned_paths:
                if fragment in text:
                    offenders.append(text)
                    break
            if path.suffix.lower() in BANNED_SUFFIXES:
                offenders.append(text)
            if path.suffix.lower() == ".json":
                allowed = False
                for allowed_dir in ALLOWED_JSON_DIRS:
                    try:
                        path.relative_to(allowed_dir)
                        allowed = True
                        break
                    except ValueError:
                        continue
                if not allowed:
                    offenders.append(text)
            if _should_scan_text_content(path):
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for fragment in banned_paths:
                    if fragment in content:
                        offenders.append(f"{text} (content: {fragment})")
                        break
                if home_marker in content:
                    offenders.append(f"{text} (content: home path)")
        self.assertGreater(
            audited_count,
            0,
            "privacy audit scanned zero publishable files",
        )
        self.assertEqual(offenders, [])

    def test_readme_svg_references_resolve(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for rel in README_SVG_REFS:
            self.assertIn(rel, readme, f"README missing reference to {rel}")
            path = ROOT / rel
            self.assertTrue(path.is_file(), f"missing README asset: {rel}")
            ET.parse(path)

    def test_svg_assets_are_self_contained(self) -> None:
        assets = ROOT / "docs" / "assets"
        svgs = sorted(assets.glob("*.svg"))
        self.assertEqual(
            [path.name for path in svgs],
            ["how-viajante-works.svg", "viajante-hero.svg"],
        )
        for path in svgs:
            root = ET.parse(path).getroot()
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("<script", text.lower())
            for element in root.iter():
                self.assertNotEqual(
                    element.tag,
                    f"{SVG_NS}image",
                    f"{path.name} contains embedded image",
                )
                for name, value in element.attrib.items():
                    if name.endswith("href"):
                        self.assertFalse(value.startswith(("http://", "https://", "//", "data:")))
                if element.tag == f"{SVG_NS}text":
                    font_size = element.attrib.get("font-size")
                    self.assertIsNotNone(font_size, f"{path.name} text missing font-size")
                    self.assertGreaterEqual(float(font_size), 18)
            self.assertTrue(root.findall(f"{SVG_NS}title"))
            self.assertTrue(root.findall(f"{SVG_NS}desc"))


if __name__ == "__main__":
    unittest.main()
