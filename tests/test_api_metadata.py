"""Test the real API patch helpers; real-model parity is a separate native gate."""

import ast
import copy
from pathlib import Path
from types import SimpleNamespace as Object
import unittest

PATCH = (
    Path(__file__).resolve().parents[1]
    / "examples/upstream/patches/analyzer-api-base64-v2.patch"
)


def row(
    kind="BASE64_DATA", start=20, end=27, source="structural", rule=None, declared=False
):
    return Object(
        entity_type=kind,
        start=start,
        end=end,
        recognition_metadata={
            "source": source,
            "deterministic_rule_id": rule,
            "encoded_container": declared,
        },
    )


class Base64:
    supported_language = "ru"
    supported_entities = ["BASE64_DATA", "SECRET_KEY"]

    def analyze_declared(self, text, entities):
        return [row(rule="base64.declared", declared=True)]

    def analyze(self, *args):
        raise AssertionError("metadata must not run content detection")

    def analyze_document(self, *args):
        raise AssertionError("metadata must reuse the document pass")


def helpers(recognizers):
    lines = PATCH.read_text().splitlines()
    start = lines.index("+def _scanner_declared_rule_ids(request, document_results):")
    added = []
    for line in lines[start:]:
        if not line.startswith("+"):
            break
        added.append(line[1:])
    tree = ast.parse("\n".join(added))
    assert [n.name for n in tree.body] == [
        "_scanner_declared_rule_ids",
        "_scanner_rule_id",
    ]
    namespace = {
        "analyzer": Object(registry=Object(recognizers=recognizers)),
        "Base64DataRecognizer": Base64,
        "detection_source": lambda r: r.recognition_metadata["source"],
        "SOURCE_STRUCTURAL": "structural",
    }
    exec(compile(tree, str(PATCH), "exec"), namespace)
    return namespace["_scanner_declared_rule_ids"], namespace["_scanner_rule_id"]


class APIMetadataTests(unittest.TestCase):
    def test_document_rule_is_stable_without_mutating_results(self):
        declarations, rule_id = helpers([Base64()])
        request = Object(text='{"base64":"example"}', language="ru")
        document = [row(rule="base64.declared-json", declared=True)]
        before = copy.deepcopy(document[0].__dict__)
        rules = declarations(request, document)
        self.assertEqual(rule_id(row(), rules), "base64.declared-json")
        self.assertEqual(
            rule_id(row(rule="base64.declared"), rules), "base64.declared-json"
        )
        self.assertEqual(document[0].__dict__, before)
        self.assertEqual(rule_id(row(), declarations(request, [])), "base64.declared")

    def test_ner_native_different_spans_and_cascade_are_not_relabelled(self):
        declarations, rule_id = helpers([Base64()])
        rules = declarations(
            Object(text="synthetic", language="ru"),
            [row(rule="base64.logistic-cascade")],
        )
        for source in ("ner", "native_credential"):
            self.assertEqual(
                rule_id(row(source=source, rule="original"), rules), "original"
            )
        self.assertIsNone(rule_id(row(end=28), rules))
        self.assertIsNone(rule_id(row(kind="SECRET_KEY"), rules))
        self.assertEqual(
            rule_id(row(start=30, end=50, rule="base64.logistic-cascade"), rules),
            "base64.logistic-cascade",
        )

    def test_other_registry_language_is_ignored(self):
        declarations, rule_id = helpers([Base64(), Object(supported_language="ru")])
        self.assertEqual(declarations(Object(text="synthetic", language="en"), []), {})
        self.assertIsNone(rule_id(row(), {}))


if __name__ == "__main__":
    unittest.main()
