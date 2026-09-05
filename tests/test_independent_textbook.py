"""Regression cases for independently usable assessment paths."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("apparatus", ROOT / "tools/validate_textbook_apparatus.py")
apparatus = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = apparatus
SPEC.loader.exec_module(apparatus)
LINK_SPEC = importlib.util.spec_from_file_location("anchors", ROOT / "tools/validate_slide_textbook_anchors.py")
anchors = importlib.util.module_from_spec(LINK_SPEC)
LINK_SPEC.loader.exec_module(anchors)


class AssessmentPaths(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "docs/part2/ch03.md").read_text()

    def test_authored_chapters_meet_standard(self):
        for path in apparatus.DEFAULT_CHAPTERS:
            with self.subTest(chapter=path.stem):
                self.assertEqual(apparatus.standard_requirement_errors((ROOT / path).read_text()), [])

    def test_missing_second_written_answer_is_rejected(self):
        start = self.text.index("5. **오답을 이용한 수정")
        end = self.text.index("## 요약", start)
        errors = apparatus.standard_requirement_errors(self.text[:start] + self.text[end:])
        self.assertTrue(any("at least 2 constructed-response" in error for error in errors))

    def test_dead_assessment_reference_is_rejected(self):
        text = self.text.replace("형성 평가 3번, 5번 |", "형성 평가 99번, 5번 |", 1)
        self.assertTrue(any("missing formative assessment" in error for error in apparatus.standard_requirement_errors(text)))

    def test_duplicate_number_is_rejected(self):
        text = self.text.replace("5. **오답을 이용한 수정", "4. **오답을 이용한 수정")
        self.assertTrue(any("numbering" in error for error in apparatus.standard_requirement_errors(text)))

    def test_rendered_deck_links_and_html_links_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "deck.html"
            path.write_text('''<a href="/book/#old">교재</a>
                link: {href: "/book/#new"},
                "link": {"href": "/book/#quoted"},
                <a href="/book/#old">중복</a>''')
            self.assertEqual(anchors.deep_links(path), ["/book/#old", "/book/#new", "/book/#quoted"])


if __name__ == "__main__":
    unittest.main()
