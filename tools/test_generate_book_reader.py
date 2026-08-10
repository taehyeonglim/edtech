#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "tools" / "generate_book_reader.py"
SPEC = importlib.util.spec_from_file_location("test_book_reader_generator", GENERATOR_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("could not load book reader generator")
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


class GenerateBookReaderTest(unittest.TestCase):
    def run_generator(self, arguments: list[str]) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return generator.main(arguments)

    def test_check_accepts_byte_identical_generated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reader_dir = Path(temporary_directory) / "book-reader"
            with mock.patch.object(generator, "READER_DIR", reader_dir):
                self.assertEqual(self.run_generator(["--mode", "release", "--write"]), 0)
                expected = {
                    path.relative_to(reader_dir): path.read_bytes()
                    for path in reader_dir.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(self.run_generator(["--mode", "release", "--check"]), 0)
                for index in range(1, 12):
                    chapter_text = (reader_dir / f"ch{index:02d}" / "index.html").read_text(encoding="utf-8")
                    for marker in (
                        "chapter_id",
                        "objectives",
                        "prework_minutes",
                        "confirmed_date",
                        "review_date",
                    ):
                        self.assertNotRegex(chapter_text, rf"\b{marker}\s*:")
                self.assertEqual(
                    {
                        path.relative_to(reader_dir): path.read_bytes()
                        for path in reader_dir.rglob("*")
                        if path.is_file()
                    },
                    expected,
                )
    def test_check_never_creates_missing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reader_dir = Path(temporary_directory) / "book-reader"
            with mock.patch.object(generator, "READER_DIR", reader_dir):
                self.assertEqual(self.run_generator(["--mode", "release", "--check"]), 1)
            self.assertFalse(reader_dir.exists())

    def test_check_reports_stale_output_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reader_dir = Path(temporary_directory) / "book-reader"
            with mock.patch.object(generator, "READER_DIR", reader_dir):
                self.assertEqual(self.run_generator(["--mode", "release", "--write"]), 0)
                stale_path = reader_dir / "ch01" / "index.html"
                stale_path.write_text("stale output\n", encoding="utf-8")
                before_check = stale_path.read_bytes()
                self.assertEqual(self.run_generator(["--mode", "release", "--check"]), 1)
                self.assertEqual(stale_path.read_bytes(), before_check)

    def test_output_dir_isolated_from_tracked_reader(self) -> None:
        tracked_paths = [generator.READER_DIR / "index.html", generator.READER_DIR / "reader-data.json"]
        tracked_paths.extend(generator.READER_DIR / f"ch{index:02d}" / "index.html" for index in range(1, 12))
        before = {path: path.read_bytes() for path in tracked_paths}
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "candidate-reader"
            self.assertEqual(
                self.run_generator(["--mode", "release", "--write", "--output-dir", str(output_dir)]),
                0,
            )
            self.assertEqual(len(list(output_dir.rglob("*.html"))) + int((output_dir / "reader-data.json").is_file()), 13)
        self.assertEqual({path: path.read_bytes() for path in tracked_paths}, before)

    def chapter(self) -> generator.Chapter:
        return generator.Chapter(
            index=1,
            title="Chapter",
            source=Path("part1/ch01.md"),
            part=1,
            slug="ch01",
        )

    def test_render_markdown_removes_valid_front_matter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            docs_dir = Path(temporary_directory)
            source = docs_dir / "part1" / "ch01.md"
            source.parent.mkdir()
            source.write_text(
                "---\nchapter_id: ch01\nobjectives: [learn]\n---\n# Visible body\n",
                encoding="utf-8",
            )
            errors: list[str] = []
            with mock.patch.object(generator, "DOCS_DIR", docs_dir):
                rendered = generator.render_markdown(self.chapter(), [], errors)
        self.assertEqual(errors, [])
        self.assertIn("<h1>Visible body</h1>", rendered)
        self.assertNotIn("chapter_id", rendered)
        self.assertNotIn("objectives", rendered)

    def test_unclosed_front_matter_fails_closed(self) -> None:
        errors: list[str] = []
        body = generator.split_front_matter(self.chapter(), "---\nchapter_id: ch01\n", errors)
        self.assertIsNone(body)
        self.assertEqual(errors, ["docs/part1/ch01.md: unclosed YAML front matter"])

    def test_duplicate_front_matter_key_fails_closed(self) -> None:
        errors: list[str] = []
        body = generator.split_front_matter(
            self.chapter(),
            "---\nchapter_id: ch01\nchapter_id: ch01\n---\n# body\n",
            errors,
        )
        self.assertIsNone(body)
        self.assertEqual(len(errors), 1)
        self.assertIn("duplicate front matter key", errors[0])

    def test_missing_required_chapter_id_fails_closed(self) -> None:
        errors: list[str] = []
        body = generator.split_front_matter(self.chapter(), "---\nobjectives: []\n---\n# body\n", errors)
        self.assertIsNone(body)
        self.assertIn("missing required key: chapter_id", errors[0])

if __name__ == "__main__":
    unittest.main()
