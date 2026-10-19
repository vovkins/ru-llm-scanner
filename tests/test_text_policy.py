import codecs
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_fixtures import RepoFixture
from ru_llm_scanner.git_plan import plan_snapshot
from ru_llm_scanner.git_repository import GitRepository
from ru_llm_scanner.text_policy import (
    EncodingOverride,
    Glob,
    TextError,
    TextPolicy,
    prepare_content,
    unsupported_format,
)


class ScopeTests(unittest.TestCase):
    def test_globs_match_segments_unicode_controls_and_zero_directory_levels(self):
        for pattern, path, expected in (
            ("**", ".hidden", True),
            ("**/*.py", "main.py", True),
            ("**/*.py", "a/b/main.py", True),
            ("src/**/x?", "src/x1", True),
            ("src/**/x?", "src/a/b/x2", True),
            ("src/*", "src/a/b", False),
            ("*.PY", "a.py", False),
            ("**", "tab\tline\nname", True),
            ("**/ю?", "a/юя", True),
            ("literal-\\xff", "literal-\\xff", True),
            ("a/**/b", "a/b", True),
            ("a/**/b", "a/x/c", False),
        ):
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(Glob(pattern).matches(path), expected)

    def test_invalid_patterns_scope_codecs_and_normalization(self):
        for value in (
            "",
            "/abs",
            "a//b",
            "../x",
            "a/./b",
            "a/**suffix",
            "a/[ab]",
            "!excluded",
            "nul\0name",
        ):
            with self.subTest(value=value), self.assertRaises(TextError):
                Glob(value)
        for value in (
            "not-a-codec",
            "base64_codec",
            "hex_codec",
            "zlib_codec",
            "rot_13",
        ):
            with self.subTest(codec=value), self.assertRaises(TextError):
                EncodingOverride("**", value)
        for kwargs in (
            {"max_file_bytes": True},
            {"max_file_bytes": 0},
            {"include": "**"},
            {"policy_version": "future"},
        ):
            with self.assertRaises(TextError):
                TextPolicy(**kwargs)
        p = TextPolicy(
            include=("**", "**"),
            exclude=("z", "a", "z"),
            encoding_overrides=(EncodingOverride("legacy/**", "windows-1251"),),
        )
        self.assertEqual(p.include, ("**",))
        self.assertEqual(p.exclude, ("a", "z"))
        self.assertEqual(p.encoding_for("legacy/file"), "cp1251")

    def test_multiple_encoding_overrides_conflict_only_on_intersecting_path(self):
        p = TextPolicy(
            encoding_overrides=(
                EncodingOverride("legacy/**", "cp1251"),
                EncodingOverride("**/*.txt", "utf8"),
            )
        )
        self.assertEqual(p.encoding_for("legacy/file"), "cp1251")
        with self.assertRaises(TextError) as error:
            p.encoding_for("legacy/file.txt")
        self.assertEqual(error.exception.code, "encoding_conflict")


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = RepoFixture(Path(self.temp.name) / "repo")

    def scan(self, files, policy=None):
        oid = self.fixture.commit(files)
        with GitRepository(self.fixture.root) as repo:
            return {
                p.selection.entry.path: p.content
                for p in plan_snapshot(repo, oid).prepare(repo, policy)
            }

    def test_utf8_empty_and_text_with_binary_extensions_preserve_whole_content(self):
        text = "ФИО 😀 e\u0301\r\nsecond\rthird\n\n"
        result = self.scan(
            {
                b"empty": b"",
                b"source.pdf": text.encode(),
                b"archive.zip": b"ordinary source",
                b".hidden": b"hidden",
                b"no-extension": b"plain",
            }
        )
        self.assertTrue(all(c.state == "ready" for c in result.values()))
        self.assertEqual(result["source.pdf"].text, text)
        self.assertEqual(result["empty"].text, "")

    def test_all_boms_decoded_and_only_initial_bom_removed(self):
        text = "😀 ФИО\r\n\ufeffe\u0301"
        data = {
            b"utf8": codecs.BOM_UTF8 + text.encode(),
            b"utf16le": codecs.BOM_UTF16_LE + text.encode("utf-16-le"),
            b"utf16be": codecs.BOM_UTF16_BE + text.encode("utf-16-be"),
            b"utf32le": codecs.BOM_UTF32_LE + text.encode("utf-32-le"),
            b"utf32be": codecs.BOM_UTF32_BE + text.encode("utf-32-be"),
        }
        result = self.scan(data)
        for name, c in result.items():
            with self.subTest(name=name):
                self.assertEqual(c.state, "ready")
                self.assertEqual(c.text, text)

    def test_explicit_legacy_wide_encoding_and_bom_compatibility(self):
        text = "Синтетический текст\r\n"
        p = TextPolicy(
            encoding_overrides=(
                EncodingOverride("legacy/**", "cp1251"),
                EncodingOverride("wide", "utf-16-le"),
                EncodingOverride("bom", "utf-16"),
            )
        )
        result = self.scan(
            {
                b"legacy/a": text.encode("cp1251"),
                b"wide": text.encode("utf-16-le"),
                b"bom": codecs.BOM_UTF16_BE + text.encode("utf-16-be"),
            },
            p,
        )
        self.assertTrue(all(c.text == text for c in result.values()))
        conflict = self.scan({b"bom": codecs.BOM_UTF8 + b"fixture"}, p)["bom"]
        self.assertEqual(
            (conflict.state, conflict.reason), ("error", "encoding_conflict")
        )

    def test_decode_error_nul_truncated_wide_surrogates_and_no_silent_legacy_fallback(
        self,
    ):
        data = {
            b"legacy": "Привет".encode("cp1251"),
            b"bad": b"bad\xffutf8",
            b"nul": b"text\0data",
            b"late-nul": b"a" * 9000 + b"\0",
            b"truncated": codecs.BOM_UTF16_LE + b"x",
            b"surrogate": codecs.BOM_UTF16_LE + b"\0\xd8",
        }
        result = self.scan(data)
        for name in ("legacy", "bad", "truncated", "surrogate"):
            self.assertEqual(
                (result[name].state, result[name].reason), ("error", "decode_error")
            )
        for name in ("nul", "late-nul"):
            self.assertEqual(
                (result[name].state, result[name].reason), ("unsupported", "binary")
            )
        self.assertNotIn("bad", repr(result["bad"]))

    def test_each_magic_signature_and_truncated_false_signatures(self):
        cases = [
            (b"%PDF-1.7", "pdf"),
            (b"PK\x03\x04", "archive"),
            (b"PK\x05\x06", "archive"),
            (b"PK\x07\x08", "archive"),
            (b"\x1f\x8b", "archive"),
            (b"7z\xbc\xaf\x27\x1c", "archive"),
            (b"Rar!", "archive"),
            (b"x" * 257 + b"ustar", "archive"),
            (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "office"),
            (b"\x89PNG\r\n\x1a\n", "image"),
            (b"\xff\xd8\xff", "image"),
            (b"GIF87a", "image"),
            (b"GIF89a", "image"),
            (b"II\x2a\0", "image"),
            (b"MM\0\x2a", "image"),
            (b"RIFFxxxxWEBP", "image"),
        ]
        result = self.scan({str(i).encode(): raw for i, (raw, _) in enumerate(cases)})
        for i, (_, reason) in enumerate(cases):
            with self.subTest(i=i):
                self.assertEqual(
                    (result[str(i)].state, result[str(i)].reason),
                    ("unsupported", reason),
                )
        for raw in (
            b"%PDF",
            b"PK",
            b"RIFFxxxxWEB",
            b"GIF89",
            b"7z\xbc",
            b"text before %PDF-",
            b"x" * 256 + b"ustar",
        ):
            self.assertIsNone(unsupported_format(raw, complete=True))

    def test_lfs_full_canonical_extensions_and_near_matches(self):
        header = b"version https://git-lfs.github.com/spec/v1\n"
        ending = b"oid sha256:" + b"a" * 64 + b"\nsize 123\n"
        extension = b"ext-0-foo sha256:" + b"b" * 64 + b"\n"
        valid = header + extension + ending
        result = self.scan(
            {
                b"pointer": valid,
                b"plain": header + ending + b"extra text\n",
                b"fragment": header,
                b"wrong-order": extension + header + ending,
                b"crlf": valid.replace(b"\n", b"\r\n"),
                b"duplicate": header + extension + extension + ending,
            }
        )
        self.assertEqual(result["pointer"].reason, "lfs_pointer")
        self.assertTrue(
            all(v.state == "ready" for k, v in result.items() if k != "pointer")
        )
        self.assertIsNone(unsupported_format(valid, complete=False))

    def test_modes_never_read_symlink_submodule_or_external_content(self):
        f = self.fixture
        oid = f.commit(
            {
                b"link": ("120000", b"/external/sentinel"),
                b"module": ("160000", "0" * 40),
            }
        )
        with GitRepository(f.root) as repo:
            entries = repo.snapshot(oid).entries
            with patch.object(
                repo,
                "open_object",
                side_effect=AssertionError("must not open special object"),
            ):
                content = [prepare_content(repo, e, TextPolicy()) for e in entries]
        self.assertEqual([c.reason for c in content], ["symlink", "submodule"])

    def test_large_text_errors_but_large_binary_only_reads_probe_and_reader_recovers(
        self,
    ):
        f = self.fixture
        oid = f.commit(
            {
                b"binary": b"%PDF-" + b"x" * 200000,
                b"large-text": b"x" * 200000,
                b"small": b"fine",
            }
        )
        with GitRepository(f.root) as repo:
            plan = plan_snapshot(repo, oid)
            reads = []
            original = repo.open_object

            def opened(*args):
                obj = original(*args)
                read = obj.read

                def counted(n):
                    raw = read(n)
                    reads.append(len(raw))
                    return raw

                obj.read = counted
                return obj

            with patch.object(repo, "open_object", side_effect=opened):
                result = {
                    p.selection.entry.path: p.content
                    for p in plan.prepare(repo, TextPolicy(max_file_bytes=10000))
                }
            self.assertEqual(result["binary"].reason, "pdf")
            self.assertEqual(result["large-text"].reason, "file_too_large")
            self.assertEqual(result["small"].text, "fine")
            self.assertLessEqual(sum(reads), 8192 * 2 + 4)
            self.assertNotIn("fine", repr(result["small"]))

    def test_encoding_conflict_is_per_file_and_later_files_still_prepare(self):
        policy = TextPolicy(
            encoding_overrides=(
                EncodingOverride("bad*", "utf8"),
                EncodingOverride("*.txt", "cp1251"),
            )
        )
        result = self.scan({b"bad.txt": b"fixture", b"good": b"other fixture"}, policy)
        self.assertEqual(
            (result["bad.txt"].state, result["bad.txt"].reason),
            ("error", "encoding_conflict"),
        )
        self.assertEqual(result["good"].state, "ready")


if __name__ == "__main__":
    unittest.main()
