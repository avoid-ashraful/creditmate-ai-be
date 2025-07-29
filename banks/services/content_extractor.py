"""
Content extraction service for various file types.
"""

import logging
from io import BytesIO
from typing import Optional, Tuple

from ..enums import ContentType
from ..exceptions import ContentExtractionError, FileFormatError, NetworkError

# Optional imports for content extraction
try:
    import requests
except ImportError:
    requests = None

try:
    import magic
except ImportError:
    magic = None

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

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Service for extracting content from various file types."""

    def __init__(self):
        """Initialize the content extractor."""
        if requests is None:
            raise ImportError("requests library is required but not installed")
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )

    def extract_content(self, url: str, content_type: str) -> Tuple[str, str]:
        """
        Extract content from URL based on content type.

        Args:
            url (str): The URL to extract content from
            content_type (str): The type of content to extract

        Returns:
            Tuple[str, str]: Raw content and extracted text content

        Raises:
            NetworkError: For network-related errors
            ContentExtractionError: For content extraction errors
            FileFormatError: For unsupported file formats
        """
        raw_content = self._fetch_content(url)
        extracted_content = self._process_content(raw_content, content_type, url)

        return raw_content.decode("utf-8", errors="ignore"), extracted_content

    def _fetch_content(self, url: str) -> bytes:
        """
        Fetch raw content from URL.

        Args:
            url (str): The URL to fetch content from

        Returns:
            bytes: Raw content from the URL

        Raises:
            NetworkError: For network-related errors
            ContentExtractionError: For HTTP errors
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except requests.exceptions.Timeout as e:
            raise NetworkError(
                f"Timeout while fetching {url}", {"url": url, "timeout": 30}
            ) from e
        except requests.exceptions.ConnectionError as e:
            raise NetworkError(
                f"Connection error while fetching {url}", {"url": url}
            ) from e
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise ContentExtractionError(
                    f"URL not found: {url}", {"url": url, "status_code": 404}
                ) from e
            elif e.response.status_code >= 500:
                raise NetworkError(
                    f"Server error for {url}: {e.response.status_code}",
                    {"url": url, "status_code": e.response.status_code},
                ) from e
            else:
                raise ContentExtractionError(
                    f"HTTP error for {url}: {e.response.status_code}",
                    {"url": url, "status_code": e.response.status_code},
                ) from e
        except Exception as e:
            raise ContentExtractionError(
                f"Unexpected error extracting content from {url}", {"url": url}
            ) from e

    def _process_content(self, raw_content: bytes, content_type: str, url: str) -> str:
        """
        Process raw content based on content type.

        Args:
            raw_content (bytes): Raw content to process
            content_type (str): Type of content
            url (str): Original URL for error reporting

        Returns:
            str: Extracted text content

        Raises:
            FileFormatError: For unsupported content types
            ContentExtractionError: For processing errors
        """
        try:
            if content_type == ContentType.PDF:
                return self._extract_pdf_content(raw_content)
            elif content_type == ContentType.WEBPAGE:
                return self._extract_webpage_content(
                    raw_content.decode("utf-8", errors="ignore")
                )
            elif content_type == ContentType.IMAGE:
                return self._extract_image_content(raw_content)
            elif content_type == ContentType.CSV:
                return self._extract_csv_content(raw_content)
            else:
                # Auto-detect content type if not specified correctly
                detected_type = self._detect_content_type(raw_content)
                if detected_type:
                    return self._process_content(raw_content, detected_type, url)
                else:
                    raise FileFormatError(
                        f"Unable to detect content type for {url}",
                        {"url": url, "content_type": content_type},
                    )
        except (ContentExtractionError, NetworkError, FileFormatError):
            raise
        except Exception as e:
            raise ContentExtractionError(
                f"Error processing content from {url}",
                {"url": url, "content_type": content_type},
            ) from e

    def _extract_pdf_content(self, raw_content: bytes) -> str:
        """
        Extract text content from PDF.

        Args:
            raw_content (bytes): Raw PDF content

        Returns:
            str: Extracted text from PDF
        """
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
        """
        Extract text content from HTML webpage.

        Args:
            html_content (str): HTML content to process

        Returns:
            str: Cleaned text content
        """
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
        """
        Extract text content from image using OCR.

        Args:
            raw_content (bytes): Raw image content

        Returns:
            str: Text extracted from image
        """
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
        """
        Extract content from CSV file.

        Args:
            raw_content (bytes): Raw CSV content

        Returns:
            str: Processed CSV content
        """
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
        """
        Detect content type from raw content.

        Args:
            raw_content (bytes): Raw content to analyze

        Returns:
            Optional[str]: Detected content type or None
        """
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
