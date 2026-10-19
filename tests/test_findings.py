import dataclasses
import hashlib
import json
import unittest

from ru_llm_scanner.analyzer import AnalysisError, Detection
from ru_llm_scanner.findings import LineIndex, make_findings
from ru_llm_scanner.git_repository import GitEntry


class FindingTests(unittest.TestCase):
    def test_independent_unicode_crlf_cr_lf_coordinates_context_and_eof(self):
        text = "😀a\r\nB\rC\nend"
        index = LineIndex(text)
        self.assertEqual(
            [index.position(n) for n in (0, 1, 2, 3, 4, 5, 6, 7, 8, 11)],
            [
                (1, 1),
                (1, 2),
                (1, 3),
                (1, 4),
                (2, 1),
                (2, 2),
                (3, 1),
                (3, 2),
                (4, 1),
                (4, 4),
            ],
        )
        entry = GitEntry(b"file", "100644", "a" * 40)
        detections = [
            Detection("PASSWORD", a, b, text[a:b], "source", 0.9, None)
            for a, b in ((1, 4), (4, 7), (8, 11))
        ]
        findings = make_findings(entry, "b" * 40, text, detections, context_lines=0)
        self.assertEqual(
            (
                findings[0].start_line,
                findings[0].start_column,
                findings[0].end_line,
                findings[0].end_column,
            ),
            (1, 2, 2, 1),
        )
        self.assertEqual(
            (
                findings[0].context.start_line,
                findings[0].context.end_line,
                findings[0].context.text,
            ),
            (1, 1, "😀a\r\n"),
        )
        self.assertEqual(
            (
                findings[1].context.start_line,
                findings[1].context.end_line,
                findings[1].context.text,
            ),
            (2, 3, "B\rC\n"),
        )
        self.assertEqual(findings[2].context.text, "end")
        padded = make_findings(entry, "b" * 40, text, detections, context_lines=100)
        self.assertTrue(all(f.context.text == text for f in padded))

    def test_stable_ids_raw_paths_duplicate_max_score_and_source_overlap(self):
        entry = GitEntry(b"raw-\xff", "100644", "a" * 40)
        text = "VALUE VALUE"
        first = Detection("PASSWORD", 0, 5, "VALUE", "ner", 0.5, None)
        detections = (
            first,
            dataclasses.replace(first, score=0.9),
            dataclasses.replace(first, source="future_source", category="FUTURE_LABEL"),
            dataclasses.replace(first, start=6, end=11),
            dataclasses.replace(first, rule_id="rule"),
        )
        findings = make_findings(entry, "b" * 40, text, detections, context_lines=0)
        self.assertEqual(len(findings), 4)
        selected = next(
            f
            for f in findings
            if f.category == "PASSWORD" and f.start_offset == 0 and f.rule_id is None
        )
        payload = {
            "path_bytes_b64": entry.path_bytes_b64,
            "object_oid": entry.oid,
            "category": "PASSWORD",
            "start_offset": 0,
            "end_offset": 5,
            "source": "ner",
            "rule_id": None,
        }
        expected = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
        self.assertEqual(selected.id, expected)
        self.assertEqual(selected.file_id, hashlib.sha256(entry.path_bytes).hexdigest())
        self.assertEqual(selected.score, 0.9)
        other = make_findings(
            GitEntry(b"raw-\\xff", "100644", entry.oid), "b" * 40, text, (first,)
        )[0]
        self.assertEqual(other.path, selected.path)
        self.assertNotEqual(other.id, selected.id)
        self.assertEqual(
            make_findings(entry, "c" * 40, text, (first,), context_lines=2)[0].id,
            selected.id,
        )
        self.assertNotIn("VALUE", repr(findings))
        self.assertNotIn("VALUE", repr(selected.context))

    def test_multiline_complete_value_and_empty_trailing_lines(self):
        text = "before\nKEY\nline1\nline2\nEND\n\nafter\n"
        value = "KEY\nline1\nline2\nEND"
        detection = Detection("PRIVATE_KEY", 7, 26, value, "structural", 1, None)
        f = make_findings(
            GitEntry(b"key", "100644", "a" * 40),
            "b" * 40,
            text,
            (detection,),
            context_lines=1,
        )[0]
        self.assertEqual(f.value, value)
        self.assertEqual(
            (f.start_line, f.start_column, f.end_line, f.end_column), (2, 1, 5, 4)
        )
        self.assertEqual(f.context.text, "before\nKEY\nline1\nline2\nEND\n\n")
        self.assertEqual(
            make_findings(GitEntry(b"empty", "100644", "a" * 40), "b" * 40, "", ()), ()
        )
        trailing = make_findings(
            GitEntry(b"trailing", "100644", "a" * 40),
            "b" * 40,
            "VALUE\r\n",
            (Detection("PASSWORD", 0, 7, "VALUE\r\n", "source", 1, None),),
            context_lines=2,
        )[0]
        self.assertEqual((trailing.end_line, trailing.end_column), (2, 1))
        self.assertEqual(
            (
                trailing.context.start_line,
                trailing.context.end_line,
                trailing.context.text,
            ),
            (1, 1, "VALUE\r\n"),
        )

    def test_bad_detections_are_bounded_errors(self):
        good = Detection("PASSWORD", 0, 5, "VALUE", "source", 0.9, None)
        for changes in (
            {"start": True},
            {"end": 20},
            {"end": 0},
            {"value": "SECRET_OTHER"},
            {"score": float("nan")},
            {"score": True},
            {"source": ""},
            {"rule_id": ""},
            {"category": "bad category"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(AnalysisError) as error,
            ):
                make_findings(
                    GitEntry(b"file", "100644", "a" * 40),
                    "b" * 40,
                    "VALUE",
                    (dataclasses.replace(good, **changes),),
                )
            self.assertEqual(str(error.exception), "finding_invalid_detection")


if __name__ == "__main__":
    unittest.main()
