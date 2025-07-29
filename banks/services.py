import json
import logging
from io import BytesIO
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.utils import timezone

# Optional imports for content extraction
try:
    import requests
except ImportError:
    requests = None

# Optional imports for content extraction
try:
    import magic
except ImportError:
    magic = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from credit_cards.models import CreditCard

from .enums import ContentType
from .models import BankDataSource, CrawledContent

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Service for extracting content from various file types."""

    def __init__(self):
        if requests is None:
            raise ImportError("requests library is required but not installed")
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )

    def extract_content(self, url: str, content_type: str) -> Tuple[str, str]:
        """Extract content from URL based on content type."""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            raw_content = response.content
            extracted_content = ""

            if content_type == ContentType.PDF:
                extracted_content = self._extract_pdf_content(raw_content)
            elif content_type == ContentType.WEBPAGE:
                extracted_content = self._extract_webpage_content(response.text)
            elif content_type == ContentType.IMAGE:
                extracted_content = self._extract_image_content(raw_content)
            elif content_type == ContentType.CSV:
                extracted_content = self._extract_csv_content(raw_content)
            else:
                # Auto-detect content type if not specified correctly
                detected_type = self._detect_content_type(raw_content)
                if detected_type:
                    extracted_content = self.extract_content(url, detected_type)[1]

            return raw_content.decode("utf-8", errors="ignore"), extracted_content

        except Exception as e:
            logger.error(f"Error extracting content from {url}: {str(e)}")
            raise

    def _extract_pdf_content(self, raw_content: bytes) -> str:
        """Extract text content from PDF."""
        if PdfReader is None:
            logger.warning("pypdf not installed, cannot extract PDF content")
            return ""

        try:
            pdf_file = BytesIO(raw_content)
            reader = PdfReader(pdf_file)
            text_content = ""

            for page in reader.pages:
                text_content += page.extract_text() + "\n"

            return text_content.strip()
        except Exception as e:
            logger.error(f"Error extracting PDF content: {str(e)}")
            return ""

    def _extract_webpage_content(self, html_content: str) -> str:
        """Extract text content from HTML webpage."""
        if BeautifulSoup is None:
            logger.warning("BeautifulSoup not installed, returning raw HTML")
            return html_content

        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            # Get text content
            text = soup.get_text()

            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = "\n".join(chunk for chunk in chunks if chunk)

            return text
        except Exception as e:
            logger.error(f"Error extracting webpage content: {str(e)}")
            return html_content

    def _extract_image_content(self, raw_content: bytes) -> str:
        """Extract text content from image using OCR."""
        if Image is None:
            logger.warning("PIL not installed, cannot extract text from images")
            return ""

        try:
            import pytesseract

            image = Image.open(BytesIO(raw_content))
            text = pytesseract.image_to_string(image)
            return text.strip()
        except ImportError:
            logger.warning("pytesseract not installed, cannot extract text from images")
            return ""
        except Exception as e:
            logger.error(f"Error extracting image content: {str(e)}")
            return ""

    def _extract_csv_content(self, raw_content: bytes) -> str:
        """Extract content from CSV file."""
        if pd is None:
            logger.warning("pandas not installed, returning raw CSV content")
            return raw_content.decode("utf-8", errors="ignore")

        try:
            csv_file = BytesIO(raw_content)
            df = pd.read_csv(csv_file)
            return df.to_string()
        except Exception as e:
            logger.error(f"Error extracting CSV content: {str(e)}")
            return raw_content.decode("utf-8", errors="ignore")

    def _detect_content_type(self, raw_content: bytes) -> Optional[str]:
        """Detect content type from raw content."""
        if magic is None:
            logger.warning("python-magic not installed, cannot detect content type")
            return None

        try:
            mime_type = magic.from_buffer(raw_content, mime=True)

            if mime_type == "application/pdf":
                return ContentType.PDF
            elif mime_type.startswith("text/html"):
                return ContentType.WEBPAGE
            elif mime_type.startswith("image/"):
                return ContentType.IMAGE
            elif mime_type == "text/csv":
                return ContentType.CSV

            return None
        except Exception:
            return None


class LLMContentParser:
    """Service for parsing extracted content using LLM."""

    def __init__(self):
        if genai is not None and hasattr(settings, "GEMINI_API_KEY"):
            genai.configure(api_key=settings.GEMINI_API_KEY)

    def parse_credit_card_data(self, content: str, bank_name: str) -> Dict[str, Any]:
        """Parse credit card information from extracted content using LLM."""
        if genai is None:
            logger.warning("Google Generative AI library not installed")
            return {}

        if not hasattr(settings, "GEMINI_API_KEY") or not settings.GEMINI_API_KEY:
            logger.warning("Gemini API key not configured")
            return {}

        try:
            # Initialize the Gemini model
            model = genai.GenerativeModel("gemini-1.5-flash")

            prompt = self._build_parsing_prompt(content, bank_name)

            # Generate content using Gemini
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=2000,
                ),
            )

            parsed_content = response.text

            # Clean up markdown code blocks if present
            if parsed_content.startswith("```json"):
                parsed_content = (
                    parsed_content.replace("```json", "").replace("```", "").strip()
                )
            elif parsed_content.startswith("```"):
                parsed_content = parsed_content.replace("```", "").strip()

            # Try to parse as JSON
            try:
                return json.loads(parsed_content)
            except json.JSONDecodeError:
                # If not valid JSON, wrap in a structure
                return {"raw_parsed_content": parsed_content}

        except Exception as e:
            logger.error(f"Error parsing content with LLM: {str(e)}")
            return {"error": str(e)}

    def _build_parsing_prompt(self, content: str, bank_name: str) -> str:
        """Build the prompt for LLM parsing."""
        return f"""
Extract credit card information from the following content for {bank_name}.

Please extract the following information for each credit card and return as JSON:
- name: Credit card name
- annual_fee: Annual fee (numeric value, 0 if free)
- interest_rate_apr: Interest rate APR (percentage)
- lounge_access_international: Number of international lounge visits
- lounge_access_domestic: Number of domestic lounge visits
- cash_advance_fee: Cash advance fee description
- late_payment_fee: Late payment fee description
- annual_fee_waiver_policy: Annual fee waiver conditions (JSON object)
- reward_points_policy: Reward points policy description
- additional_features: List of additional features

Return the data as a JSON array of credit card objects. If no credit card data is found, return an empty array.

Content to analyze:
{content[:4000]}  # Limit content length for API
"""


class CreditCardDataService:
    """Service for updating credit card data in the database."""

    def update_credit_card_data(self, bank_id: int, parsed_data: Dict[str, Any]) -> int:
        """Update credit card data in the database."""
        updated_count = 0

        if not isinstance(parsed_data, list):
            if "credit_cards" in parsed_data:
                parsed_data = parsed_data["credit_cards"]
            else:
                logger.warning("Parsed data is not in expected format")
                return 0

        for card_data in parsed_data:
            try:
                card, created = CreditCard.objects.update_or_create(
                    bank_id=bank_id,
                    name=card_data.get("name", ""),
                    defaults={
                        "annual_fee": self._parse_decimal(card_data.get("annual_fee", 0)),
                        "interest_rate_apr": self._parse_decimal(
                            card_data.get("interest_rate_apr", 0)
                        ),
                        "lounge_access_international": card_data.get(
                            "lounge_access_international", 0
                        ),
                        "lounge_access_domestic": card_data.get(
                            "lounge_access_domestic", 0
                        ),
                        "cash_advance_fee": card_data.get("cash_advance_fee", ""),
                        "late_payment_fee": card_data.get("late_payment_fee", ""),
                        "annual_fee_waiver_policy": card_data.get(
                            "annual_fee_waiver_policy"
                        ),
                        "reward_points_policy": card_data.get("reward_points_policy", ""),
                        "additional_features": card_data.get("additional_features", []),
                        "is_active": True,
                    },
                )
                updated_count += 1
                logger.info(
                    f"{'Created' if created else 'Updated'} credit card: {card.name}"
                )

            except Exception as e:
                logger.error(f"Error updating credit card data: {str(e)}")
                continue

        return updated_count

    def _parse_decimal(self, value) -> float:
        """Parse decimal value from various formats."""
        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            # Remove currency symbols and percentage signs
            cleaned = value.replace("$", "").replace("%", "").replace(",", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return 0.0

        return 0.0


class BankDataCrawlerService:
    """Main service orchestrating the bank data crawling process."""

    def __init__(self):
        self.content_extractor = ContentExtractor()
        self.llm_parser = LLMContentParser()
        self.data_service = CreditCardDataService()

    def crawl_bank_data_source(self, data_source_id: int) -> bool:
        """Crawl a single bank data source."""
        try:
            data_source = BankDataSource.objects.get(id=data_source_id, is_active=True)

            logger.info(f"Starting crawl for {data_source.bank.name} - {data_source.url}")

            # Update crawl timestamp
            data_source.last_crawled_at = timezone.now()
            data_source.save(update_fields=["last_crawled_at"])

            # Extract content
            raw_content, extracted_content = self.content_extractor.extract_content(
                data_source.url, data_source.content_type
            )

            # Parse with LLM
            parsed_data = self.llm_parser.parse_credit_card_data(
                extracted_content, data_source.bank.name
            )

            # Store crawled content
            crawled_content = CrawledContent.objects.create(
                data_source=data_source,
                raw_content=raw_content,
                extracted_content=extracted_content,
                parsed_json=parsed_data,
                processing_status="processing",
            )

            # Update database
            if parsed_data and "error" not in parsed_data:
                updated_count = self.data_service.update_credit_card_data(
                    data_source.bank.id, parsed_data
                )

                crawled_content.processing_status = "completed"
                crawled_content.save(update_fields=["processing_status"])

                # Reset failed attempts on success
                data_source.reset_failed_attempts()
                data_source.last_successful_crawl_at = timezone.now()
                data_source.save(update_fields=["last_successful_crawl_at"])

                logger.info(
                    f"Successfully updated {updated_count} credit cards for {data_source.bank.name}"
                )
                return True
            else:
                crawled_content.processing_status = "failed"
                crawled_content.error_message = str(
                    parsed_data.get("error", "Failed to parse data")
                )
                crawled_content.save(update_fields=["processing_status", "error_message"])

                data_source.increment_failed_attempts()
                logger.error(f"Failed to parse data for {data_source.bank.name}")
                return False

        except BankDataSource.DoesNotExist:
            logger.error(f"BankDataSource with id {data_source_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error crawling data source {data_source_id}: {str(e)}")

            try:
                data_source = BankDataSource.objects.get(id=data_source_id)
                data_source.increment_failed_attempts()

                CrawledContent.objects.create(
                    data_source=data_source,
                    processing_status="failed",
                    error_message=str(e),
                )
            except Exception as e:
                logger.error(f"Error crawling data source {data_source_id}: {str(e)}")

            return False

    def crawl_all_active_sources(self) -> Dict[str, int]:
        """Crawl all active bank data sources."""
        active_sources = BankDataSource.objects.filter(is_active=True)

        results = {"total": active_sources.count(), "successful": 0, "failed": 0}

        for data_source in active_sources:
            if self.crawl_bank_data_source(data_source.id):
                results["successful"] += 1
            else:
                results["failed"] += 1

        logger.info(f"Crawling completed: {results}")
        return results
