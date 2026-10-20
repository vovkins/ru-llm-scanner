"""Explicit CPU-image regressions for the scanner's NER adaptation patch.

Use pytest inside the Analyzer test image, with a prepared context on PYTHONPATH.
These synthetic context-dependent logits reproduce the boundary failure without
copying real authors or changing the frozen model/corpus.
"""

import pytest
from presidio.ner.huggingface_recognizer import (
    HuggingFaceNERRecognizer,
    NERProcessingError,
)
from presidio.tests.test_ner import FakeTokenizer, GlobalLabelModel


class ContextDependentModel(GlobalLabelModel):
    def __init__(
        self,
        *,
        confirm_alternate=True,
        fail_alternate=False,
        confirm_fine=False,
        confirm_far_end=False,
    ):
        super().__init__()
        self.confirm_alternate = confirm_alternate
        self.fail_alternate = fail_alternate
        self.confirm_fine = confirm_fine
        self.confirm_far_end = confirm_far_end

    def __call__(self, **kwargs):
        result = super().__call__(**kwargs)
        for row, token_ids in enumerate(kwargs["input_ids"].tolist()):
            content = [i for i in token_ids if i >= 1000]
            start = content[0] - 1000
            if start == 32 and self.fail_alternate:
                raise RuntimeError("synthetic alternate inference failure")
            if (
                start != 320
                and not (start == 32 and self.confirm_alternate)
                and not (start == 80 and self.confirm_fine)
                and not (start == 84 and self.confirm_far_end)
            ):
                continue
            for column, token in enumerate(token_ids):
                position = token - 1000
                if 320 <= position < 325:
                    result.logits[row, column, :] = -10.0
                    result.logits[row, column, 1 if position == 320 else 2] = 10.0
        return result


def recognizer(**kwargs):
    tokenizer = FakeTokenizer([(i, i + 1) for i in range(500)])
    return HuggingFaceNERRecognizer(
        tokenizer=tokenizer, model=ContextDependentModel(**kwargs)
    )


def test_alternate_context_confirms_candidate_without_losing_tail():
    detector = recognizer()
    result = detector.analyze("x" * 500)
    assert [(r.entity_type, r.start, r.end) for r in result] == [("PERSON", 320, 325)]
    assert detector.is_ready()
    # Initial windows, then centered recovery, then alternate context.
    assert detector._model.call_count == 3


def test_absence_in_all_recovery_contexts_is_not_clean():
    detector = recognizer(confirm_alternate=False)
    with pytest.raises(NERProcessingError) as error:
        detector.analyze("x" * 500)
    assert error.value.failure_class == "window_boundary_unresolved"
    assert detector.is_ready()  # request scoped; a later request may still work


def test_fine_context_is_used_only_after_quarter_context_fails():
    detector = recognizer(confirm_alternate=False, confirm_fine=True)
    result = detector.analyze("x" * 500)
    assert [(r.entity_type, r.start, r.end) for r in result] == [("PERSON", 320, 325)]
    assert detector._model.call_count == 4


def test_far_end_of_clipped_span_is_an_independent_recovery_anchor():
    detector = recognizer(confirm_alternate=False, confirm_far_end=True)
    result = detector.analyze("x" * 500)
    assert [(r.entity_type, r.start, r.end) for r in result] == [("PERSON", 320, 325)]


class MixedSpanModel(GlobalLabelModel):
    def __call__(self, **kwargs):
        result = super().__call__(**kwargs)
        for row, token_ids in enumerate(kwargs["input_ids"].tolist()):
            content = [i for i in token_ids if i >= 1000]
            start = content[0] - 1000
            spans = [(0, 800)] if start in (0, 320, 640) else []
            if start == 960:
                spans = [(960, 965)]
            if start == 672:
                # This context fits the short span, but cannot contain the long
                # original cluster. Its interior fragment must not clear it.
                spans = [(790, 795), (960, 965)]
            for column, token in enumerate(token_ids):
                for a, b in spans:
                    if a <= token - 1000 < b:
                        result.logits[row, column, :] = -10.0
                        result.logits[row, column, 1 if token - 1000 == a else 2] = 10.0
        return result


def test_nearby_short_span_does_not_bypass_long_cluster_containment():
    detector = HuggingFaceNERRecognizer(
        tokenizer=FakeTokenizer([(i, i + 1) for i in range(1300)]),
        model=MixedSpanModel(),
    )
    with pytest.raises(NERProcessingError) as error:
        detector.analyze("x" * 1300)
    assert error.value.failure_class == "window_boundary_unresolved"
    assert detector.is_ready()


def test_alternate_forward_failure_is_not_clean():
    detector = recognizer(fail_alternate=True)
    with pytest.raises(NERProcessingError) as error:
        detector.analyze("x" * 500)
    assert error.value.failure_class == "forward_pass_failed"
