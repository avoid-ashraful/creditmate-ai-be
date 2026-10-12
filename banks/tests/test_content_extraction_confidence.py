"""Phase 3 tests: content extraction confidence and multi-source validation."""

from unittest.mock import patch

import pytest

from banks.enums import ContentType
from banks.exceptions import ContentExtractionError, NetworkError
from banks.services.content_extractor import ContentExtractor

QUALITY_TEXT = (
    "SCHEDULE OF CHARGES - Credit Card annual fee interest rate APR charges "
    "cash advance table | tk. 5,000 | 20% per annum | "
) * 20


@pytest.fixture
def extractor():
    return ContentExtractor()


class TestExtractionConfidenceScore:
    """calculate_extraction_confidence must stay bounded and explainable."""

    @pytest.mark.parametrize(
        "content,method",
        [
            ("", "pdf_text"),
            ("x", "ocr"),
            ("a" * 50, "pdf_text"),
            (QUALITY_TEXT, "pdf_text"),
            (QUALITY_TEXT, "ocr"),
            (QUALITY_TEXT, "webpage"),
            (QUALITY_TEXT, "unknown"),
            (None, "csv"),
        ],
        ids=[
            "empty",
            "one-char",
            "short",
            "good-pdf",
            "good-ocr",
            "good-web",
            "good-unknown",
            "none-content",
        ],
    )
    def test_bounds_hold(self, extractor, content, method):
        score = extractor.calculate_extraction_confidence(content, method)
        assert 0.0 <= score <= 1.0

    def test_quality_text_outranks_garbage(self, extractor):
        good = extractor.calculate_extraction_confidence(QUALITY_TEXT, "pdf_text")
        bad = extractor.calculate_extraction_confidence("lorem ipsum " * 10, "pdf_text")
        assert good > bad

    def test_ocr_is_discounted(self, extractor):
        native = extractor.calculate_extraction_confidence(QUALITY_TEXT, "pdf_text")
        ocr = extractor.calculate_extraction_confidence(QUALITY_TEXT, "ocr")
        assert ocr < native


class TestExtractWithValidation:
    """Multi-source extraction keeps the highest scoring attempt."""

    def test_best_attempt_wins(self, extractor):
        weak_text = "tiny"
        with (
            patch.object(extractor, "_fetch_content", return_value=b"%PDF-fake"),
            patch.object(extractor, "_process_content", return_value=weak_text),
            patch.object(
                extractor, "_extract_pdf_with_ocr", return_value=QUALITY_TEXT
            ),
        ):
            result = extractor.extract_with_validation(
                "https://example.com/schedule.pdf", ContentType.PDF
            )

        assert result["method"] == "ocr"
        assert result["content"] == QUALITY_TEXT
        assert 0.0 <= result["confidence"] <= 1.0
        assert len(result["attempts"]) == 2
        assert {attempt["method"] for attempt in result["attempts"]} == {
            "pdf_text",
            "ocr",
        }
        assert result["raw_content"].startswith("<BINARY_CONTENT_")

    def test_native_text_wins_when_it_is_better(self, extractor):
        with (
            patch.object(extractor, "_fetch_content", return_value=b"%PDF-fake"),
            patch.object(extractor, "_process_content", return_value=QUALITY_TEXT),
            patch.object(extractor, "_extract_pdf_with_ocr", return_value="junk"),
        ):
            result = extractor.extract_with_validation(
                "https://example.com/schedule.pdf", ContentType.PDF
            )

        assert result["method"] == "pdf_text"
        assert len(result["attempts"]) == 2

    def test_ocr_failure_is_recorded_not_fatal(self, extractor):
        with (
            patch.object(extractor, "_fetch_content", return_value=b"%PDF-fake"),
            patch.object(extractor, "_process_content", return_value=QUALITY_TEXT),
            patch.object(
                extractor,
                "_extract_pdf_with_ocr",
                side_effect=RuntimeError("no tesseract"),
            ),
        ):
            result = extractor.extract_with_validation(
                "https://example.com/schedule.pdf", ContentType.PDF
            )

        assert result["method"] == "pdf_text"
        failed = [a for a in result["attempts"] if a["method"] == "ocr"]
        assert failed and failed[0]["error"] is not None

    def test_all_methods_failing_raises(self, extractor):
        with (
            patch.object(extractor, "_fetch_content", return_value=b"%PDF-fake"),
            patch.object(
                extractor, "_process_content", side_effect=ValueError("bad pdf")
            ),
            patch.object(
                extractor,
                "_extract_pdf_with_ocr",
                side_effect=ValueError("no text"),
            ),
        ):
            with pytest.raises(ContentExtractionError):
                extractor.extract_with_validation(
                    "https://example.com/schedule.pdf", ContentType.PDF
                )

    def test_fetch_failure_propagates_as_network_error(self, extractor):
        with patch.object(
            extractor,
            "_fetch_content",
            side_effect=NetworkError("offline", {"url": "x"}),
        ):
            with pytest.raises(NetworkError):
                extractor.extract_with_validation(
                    "https://example.com/x.pdf", ContentType.PDF
                )

    def test_single_attempt_for_non_pdf_types(self, extractor):
        with (
            patch.object(extractor, "_fetch_content", return_value=b"<html></html>"),
            patch.object(extractor, "_process_content", return_value=QUALITY_TEXT),
        ):
            result = extractor.extract_with_validation(
                "https://example.com/page", ContentType.WEBPAGE
            )

        assert result["method"] == "webpage"
        assert len(result["attempts"]) == 1
        assert result["raw_content"] == "<html></html>"


class TestMethodMapping:
    @pytest.mark.parametrize(
        "content_type,expected",
        [
            (ContentType.PDF, "pdf_text"),
            (ContentType.WEBPAGE, "webpage"),
            (ContentType.IMAGE, "image_ocr"),
            (ContentType.CSV, "csv"),
            ("something-else", "unknown"),
            (None, "unknown"),
        ],
    )
    def test_method_for_content_type(self, content_type, expected):
        assert ContentExtractor._method_for_content_type(content_type) == expected

    @pytest.mark.parametrize(
        "content_type,placeholder_expected",
        [(ContentType.PDF, True), (ContentType.IMAGE, True), (ContentType.CSV, False)],
    )
    def test_raw_content_placeholder_avoids_binary_in_db(
        self, content_type, placeholder_expected
    ):
        placeholder = ContentExtractor._raw_content_placeholder(
            b"\x00\x01binary", content_type
        )
        if placeholder_expected:
            assert placeholder.startswith("<BINARY_CONTENT_")
            assert "\x00" not in placeholder
        else:
            assert isinstance(placeholder, str)
