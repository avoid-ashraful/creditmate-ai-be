"""Vision rendering and crawler safety with no network, vendor or CLI calls."""

import json
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from banks.exceptions import ContentExtractionError
from banks.factories import BankDataSourceFactory
from banks.models import CrawledContent, ReviewQueue
from banks.services import content_extractor as content_module
from banks.services.bank_data_crawler import BankDataCrawlerService
from banks.services.content_extractor import ContentExtractor
from banks.services.llm_parser import LLMContentParser
from banks.services.prompt_templates import BankSpecificPrompts
from banks.validators import CreditCardDataValidator
from common.llm.budget import llm_call_budget
from common.llm.exceptions import LLMRateLimitError
from common.llm.services import LLMOrchestrator
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard


def png(color="white", size=(10, 10)):
    """Create a small deterministic image source."""
    output = BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


def make_crawler(cards=None):
    """Use real parsing, validation and writes with mocked external boundaries."""
    fake = MagicMock()
    fake.supports_images = True
    fake.is_available.return_value = True
    fake.validate_response.return_value = True
    fake.generate_from_images.return_value = json.dumps(cards or [])
    orchestrator = LLMOrchestrator.__new__(LLMOrchestrator)
    orchestrator.providers = {"vision_test": fake}
    parser = LLMContentParser.__new__(LLMContentParser)
    parser.orchestrator = orchestrator
    parser.validator = CreditCardDataValidator()
    parser.prompt_templates = BankSpecificPrompts()
    extractor = ContentExtractor()
    extractor._fetch_content = MagicMock(return_value=png())
    extractor._extract_image_content = MagicMock(return_value="")
    crawler = BankDataCrawlerService(
        content_extractor=extractor, llm_parser=parser, multi_pass_extractor=MagicMock()
    )
    return crawler, fake


def test_direct_image_is_bounded_png(tmp_path):
    paths = ContentExtractor.prepare_vision_images(png(size=(4200, 1)), "image", tmp_path)
    assert len(paths) == 4
    with Image.open(paths[0]) as image:
        assert image.format == "PNG"
        assert image.size == (4000, 1)


def test_detail_tiles_preserve_small_table_text_without_losing_page_edges(tmp_path):
    overview = tmp_path / "page-1.png"
    image = Image.new("RGB", (2500, 2200), "white")
    image.putpixel((2499, 2199), (0, 0, 255))
    image.save(overview)
    paths = ContentExtractor._add_vision_details([overview])
    assert paths[0] == overview
    assert len(paths) > 1
    for path in paths[1:]:
        with Image.open(path) as tile:
            assert max(tile.size) <= 1600
    with Image.open(paths[-1]) as last:
        assert last.getpixel((last.width - 1, last.height - 1)) == (0, 0, 255)


def test_poppler_is_bounded_and_pages_are_numerically_ordered(tmp_path):
    def render(command, **kwargs):
        assert command[command.index("-r") + 1] == "200"
        assert command[command.index("-l") + 1] == "4"
        assert command[command.index("-scale-to") + 1] == "4000"
        assert kwargs["timeout"] == 90
        assert kwargs["check"]
        for index in [4, 2, 1, 3]:
            (tmp_path / f"page-{index}.png").write_bytes(png())

    with (
        patch.object(content_module.shutil, "which", return_value="/bin/pdftoppm"),
        patch.object(content_module.subprocess, "run", side_effect=render),
    ):
        paths = ContentExtractor.prepare_vision_images(b"pdf", "pdf", tmp_path)
    assert [path.name for path in paths] == [f"page-{i}.png" for i in range(1, 5)]


def test_existing_pymupdf_fallback_caps_pages_and_dimensions(tmp_path):
    document = MagicMock()
    document.__enter__.return_value = document
    document.__len__.return_value = 8
    page = document.__getitem__.return_value
    page.rect.width, page.rect.height = 2000, 1000
    page.get_pixmap.return_value.save.side_effect = lambda path: Path(path).write_bytes(
        png()
    )
    with (
        patch.object(content_module.shutil, "which", return_value=None),
        patch("fitz.open", return_value=document),
    ):
        paths = ContentExtractor.prepare_vision_images(b"pdf", "pdf", tmp_path)
    assert len(paths) == 4
    assert page.get_pixmap.call_count == 4
    assert page.get_pixmap.call_args.kwargs["matrix"].a == 2


def test_rendering_errors_and_size_limits_are_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(content_module, "VISION_MAX_BYTES", 100)
    with pytest.raises(ContentExtractionError, match="20 MiB"):
        ContentExtractor.prepare_vision_images(b"x" * 101, "pdf", tmp_path)
    with patch.object(content_module.subprocess, "run", side_effect=OSError("missing")):
        with pytest.raises(ContentExtractionError, match="Unable to prepare"):
            ContentExtractor.prepare_vision_images(b"pdf", "pdf", tmp_path)

    def oversized_output(*args, **kwargs):
        (tmp_path / "page-1.png").write_bytes(b"x" * 101)

    with (
        patch.object(content_module.shutil, "which", return_value="/bin/pdftoppm"),
        patch.object(content_module.subprocess, "run", side_effect=oversized_output),
        patch.object(
            ContentExtractor, "_add_vision_details", side_effect=lambda paths: paths
        ),
    ):
        with pytest.raises(ContentExtractionError, match="Unable to prepare"):
            ContentExtractor.prepare_vision_images(b"pdf", "pdf", tmp_path)
    monkeypatch.setattr(content_module, "VISION_MAX_BYTES", 1)
    with pytest.raises(ContentExtractionError):
        ContentExtractor.prepare_vision_images(b"", "image", tmp_path)


def test_vision_uses_same_download_and_cleans_up_on_failure():
    extractor = ContentExtractor()
    with (
        patch.object(extractor, "_fetch_content", return_value=png()) as fetch,
        patch.object(extractor, "_extract_image_content", return_value=""),
    ):
        extractor.extract_content("https://bank.test/poster.png", "image")
        with pytest.raises(ValueError):
            with extractor.vision_images(
                "https://bank.test/poster.png", "image"
            ) as paths:
                path = paths[0]
                assert path.exists()
                raise ValueError("provider failed")
        assert not path.exists()
        fetch.assert_called_once()
        with pytest.raises(ContentExtractionError):
            with extractor.vision_images("https://other.test", "image"):
                pass


@pytest.mark.django_db
class TestVisionCrawler:
    def test_vision_preserves_verified_cards_drafts_and_sanity_rules(self):
        source = BankDataSourceFactory(content_type="image")
        verified = CreditCardFactory(bank=source.bank, name="Gold", annual_fee=1000)
        crawler, fake = make_crawler(
            [
                {"name": "Gold", "annual_fee": 2000, "interest_rate_apr": 25},
                {"name": "Platinum", "annual_fee": 3000, "interest_rate_apr": 25},
                {"name": "Odd", "annual_fee": -50, "interest_rate_apr": 25},
                {"name": "Debit Card", "annual_fee": 100, "interest_rate_apr": 25},
            ]
        )
        assert crawler.crawl_bank_data_source(source.pk)
        verified.refresh_from_db()
        assert verified.annual_fee == 1000
        assert verified.verification_status == "verified"
        assert ReviewQueue.objects.filter(
            credit_card=verified, field_name="annual_fee", proposed_value=2000.0
        ).exists()
        draft = CreditCard.objects.get(name="Platinum")
        assert draft.verification_status == "draft"
        assert not draft.is_public
        odd = CreditCard.objects.get(name="Odd")
        assert odd.annual_fee is None
        assert odd.verification_status == "needs_review"
        assert not CreditCard.objects.filter(name="Debit Card").exists()
        record = CrawledContent.objects.get()
        assert record.extraction_method == "vision"
        assert record.parsed_json_raw["provider_used"] == "vision_test"
        assert record.processing_status == "completed"
        assert (
            "annual_fee out of range"
            in record.parsed_json["credit_cards"][2]["sanity_flags"]
        )
        fake.generate_response.assert_not_called()
        assert fake.generate_from_images.call_count == 1

    @pytest.mark.parametrize(
        "failure", ["unavailable", "budget", "quota", "empty", "bad"]
    )
    def test_vision_failure_preserves_needs_multimodal_review(self, failure):
        source = BankDataSourceFactory(content_type="image", failed_attempt_count=4)
        crawler, fake = make_crawler()
        if failure == "unavailable":
            fake.supports_images = False
        elif failure == "quota":
            fake.generate_from_images.side_effect = LLMRateLimitError("429 quota")
        elif failure == "bad":
            fake.generate_from_images.return_value = "not JSON"
        with llm_call_budget(1) as budget:
            if failure == "budget":
                budget.consume()
            assert not crawler.crawl_bank_data_source(source.pk)
        record = CrawledContent.objects.get()
        assert record.processing_status == "pending"
        assert record.parsed_json["reason"] == "needs_multimodal"
        assert record.needs_manual_review
        assert ReviewQueue.objects.filter(crawled_content=record).exists()
        assert not CreditCard.objects.exists()
        source.refresh_from_db()
        assert source.failed_attempt_count == 4 and source.is_active
        fake.generate_response.assert_not_called()
        if failure in {"unavailable", "budget"}:
            fake.generate_from_images.assert_not_called()

    def test_binary_hash_detects_changed_posters_with_identical_empty_ocr(self):
        source = BankDataSourceFactory(content_type="image")
        crawler, fake = make_crawler(
            [{"name": "Gold", "annual_fee": 1000, "interest_rate_apr": 25}]
        )
        assert crawler.crawl_bank_data_source(source.pk)
        assert crawler.crawl_bank_data_source(source.pk)
        assert fake.generate_from_images.call_count == 1
        crawler.content_extractor._fetch_content.return_value = png("red")
        assert crawler.crawl_bank_data_source(source.pk)
        assert fake.generate_from_images.call_count == 2
        records = list(CrawledContent.objects.order_by("pk"))
        assert len(records) == 2
        assert records[0].content_hash != records[1].content_hash

    def test_pdf_with_empty_ocr_uses_rendered_images(self, tmp_path):
        source = BankDataSourceFactory(content_type="pdf")
        crawler, fake = make_crawler(
            [{"name": "Gold", "annual_fee": 1000, "interest_rate_apr": 25}]
        )
        crawler.content_extractor._fetch_content.return_value = b"pdf"
        image = tmp_path / "page.png"
        image.write_bytes(png())

        @contextmanager
        def images(*args):
            yield [image]

        with (
            patch.object(
                crawler.content_extractor, "_extract_pdf_content", return_value=""
            ),
            patch.object(crawler.content_extractor, "vision_images", side_effect=images),
        ):
            crawler.content_extractor.last_extraction_method = "ocr"

            # The mocked PDF extractor must report the OCR method as the real one does.
            def no_ocr(*args):
                crawler.content_extractor.last_extraction_method = "ocr"
                return ""

            with patch.object(crawler.content_extractor, "_extract_pdf_content", no_ocr):
                assert crawler.crawl_bank_data_source(source.pk)
        assert CrawledContent.objects.get().extraction_method == "vision"
        assert fake.generate_from_images.call_count == 1
