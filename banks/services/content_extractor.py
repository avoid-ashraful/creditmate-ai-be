import logging
from io import BytesIO

import magic
import pandas as pd
import requests
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader

from ..enums import ContentType
from ..exceptions import ContentExtractionError, FileFormatError, NetworkError

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Service for extracting content from various file types.

    This service handles content extraction from multiple sources including:
    - PDF documents (text extraction with OCR fallback)
    - Web pages (HTML parsing and text extraction)
    - Images (OCR text extraction)
    - CSV files (structured data parsing)
    """

    def __init__(self):
        """Initialize the content extractor.

        Sets up HTTP session with appropriate headers for web content extraction.

        Returns
        -------
        None

        Raises
        ------
        None
        """
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )

    def extract_content(self, url, content_type):
        """Extract content from URL based on content type.

        Parameters
        ----------
        url : str
            The URL to extract content from
        content_type : str
            The type of content to extract (PDF, WEBPAGE, IMAGE, CSV)

        Returns
        -------
        tuple of (str, str)
            First element is raw content (or placeholder for binary),
            second element is extracted text content

        Raises
        ------
        NetworkError
            For network-related connection or timeout errors
        ContentExtractionError
            For HTTP errors or general extraction failures
        FileFormatError
            For unsupported or undetectable file formats
        """
        raw_content = self._fetch_content(url)
        extracted_content = self._process_content(raw_content, content_type, url)

        # For binary content types, store a placeholder for raw content to avoid NUL character issues
        if content_type == ContentType.PDF or content_type == ContentType.IMAGE:
            raw_content_str = (
                f"<BINARY_CONTENT_{content_type.upper()}_SIZE_{len(raw_content)}>"
            )
        else:
            raw_content_str = raw_content.decode("utf-8", errors="ignore")

        return raw_content_str, extracted_content

    def _fetch_content(self, url):
        """Fetch raw content from URL.

        Parameters
        ----------
        url : str
            The URL to fetch content from

        Returns
        -------
        bytes
            Raw binary content retrieved from the URL

        Raises
        ------
        NetworkError
            For network timeouts or connection errors
        ContentExtractionError
            For HTTP errors (404, 500, etc.) or unexpected failures
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

    def _process_content(self, raw_content, content_type, url):
        """Process raw content based on content type.

        Parameters
        ----------
        raw_content : bytes
            Raw binary content to process
        content_type : str
            Type of content (PDF, WEBPAGE, IMAGE, CSV)
        url : str
            Original URL for error reporting and logging

        Returns
        -------
        str
            Extracted text content from the processed source

        Raises
        ------
        FileFormatError
            For unsupported or undetectable content types
        ContentExtractionError
            For processing errors during content extraction
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

    def _extract_pdf_content(self, raw_content):
        """Extract text content from PDF, with OCR fallback for image-based PDFs.

        Parameters
        ----------
        raw_content : bytes
            Raw PDF binary content

        Returns
        -------
        str
            Extracted text from PDF, using OCR fallback for image-based PDFs
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

            text_content = text_content.strip()

            # If extracted text is minimal (likely image-based PDF), try OCR
            if len(text_content) < 50:  # Threshold for minimal text
                logger.info("Minimal text extracted from PDF, attempting OCR...")
                ocr_text = self._extract_pdf_with_ocr(raw_content)
                if ocr_text and len(ocr_text) > len(text_content):
                    return ocr_text

            return text_content
        except Exception as e:
            logger.error(f"Error extracting PDF content: {str(e)}")
            # Try OCR as fallback for corrupted or complex PDFs
            logger.info("Attempting OCR fallback for PDF...")
            return self._extract_pdf_with_ocr(raw_content)

    def _extract_pdf_with_ocr(self, raw_content):
        """Extract text from image-based PDF using OCR.

        Parameters
        ----------
        raw_content : bytes
            Raw PDF binary content requiring OCR processing

        Returns
        -------
        str
            Text extracted via OCR from PDF pages converted to images
        """
        try:
            # Check if required libraries are available
            try:
                import fitz  # PyMuPDF
            except ImportError:
                logger.warning("PyMuPDF not available, cannot perform PDF OCR")
                return ""

            try:
                import pytesseract
                from PIL import Image
            except ImportError:
                logger.warning("pytesseract/PIL not available, cannot perform PDF OCR")
                return ""

            # Convert PDF pages to images and extract text with OCR
            doc = fitz.open(stream=raw_content, filetype="pdf")
            all_text = ""

            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                # Convert page to image (higher DPI for better OCR)
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(2, 2)
                )  # 2x scaling for better quality
                img_data = pix.tobytes("png")

                # Perform OCR on the image
                image = Image.open(BytesIO(img_data))
                text = pytesseract.image_to_string(image, config="--psm 6")
                all_text += text + "\n"

            doc.close()
            return all_text.strip()

        except Exception as e:
            logger.error(f"Error performing PDF OCR: {str(e)}")
            return ""

    def _extract_webpage_content(self, html_content):
        """Extract text content from HTML webpage.

        Parameters
        ----------
        html_content : str
            Raw HTML content to process and clean

        Returns
        -------
        str
            Cleaned text content with scripts/styles removed
        """
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

    def _extract_image_content(self, raw_content):
        """Extract text content from image using OCR.

        Parameters
        ----------
        raw_content : bytes
            Raw image binary content (JPEG, PNG, etc.)

        Returns
        -------
        str
            Text extracted from image using pytesseract OCR
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

    def _extract_csv_content(self, raw_content):
        """Extract content from CSV file.

        Parameters
        ----------
        raw_content : bytes
            Raw CSV binary content

        Returns
        -------
        str
            Processed CSV content as formatted string using pandas
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

    def _detect_content_type(self, raw_content):
        """Detect content type from raw content.

        Parameters
        ----------
        raw_content : bytes
            Raw binary content to analyze for type detection

        Returns
        -------
        str or None
            Detected content type (PDF, WEBPAGE, IMAGE, CSV) or None if undetectable
        """
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
