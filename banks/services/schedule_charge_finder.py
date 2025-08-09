"""
Service for finding schedule of charges/fee document URLs from bank websites.
"""

import logging
from urllib.parse import urljoin

from django.conf import settings

from ..exceptions import NetworkError

# Optional imports
try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)


class ScheduleChargeURLFinder:
    """Service for finding schedule of charges/fee document URLs using AI.

    This service analyzes bank websites to locate schedule of charges or
    fee documents using AI-powered content analysis and link extraction.
    """

    def __init__(self):
        """Initialize the URL finder.

        Sets up HTTP session with appropriate headers for web scraping.

        Returns
        -------
        None

        Raises
        ------
        ImportError
            If requests library is not installed
        """
        if requests is None:
            raise ImportError("requests library is required but not installed")
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )

    def find_schedule_charge_url(self, base_url):
        """Find schedule of charges URL using AI to analyze webpage content.

        Parameters
        ----------
        base_url : str
            Base URL of the bank website to analyze

        Returns
        -------
        dict
            Result dictionary containing:
            - found: bool indicating if URL was found
            - url: str with the found URL if successful
            - method: str describing the method used
            - content_type: str indicating PDF or WEBPAGE
            - error: str with error message if failed
        """
        try:
            logger.info(f"Finding schedule charge URL for: {base_url}")

            webpage_content = self._fetch_webpage_content(base_url)
            analysis_data = self._analyze_webpage_content(webpage_content, base_url)
            result = self._process_ai_analysis(analysis_data, base_url)

            return result

        except Exception as e:
            logger.error(f"Error finding schedule charge URL: {str(e)}")
            return {"found": False, "method": "error", "error": str(e)}

    def _fetch_webpage_content(self, url):
        """Fetch and parse webpage content.

        Parameters
        ----------
        url : str
            URL to fetch and parse

        Returns
        -------
        dict
            Dictionary containing webpage content and metadata:
            - html_text: raw HTML content
            - soup: BeautifulSoup parsed object
            - links: list of extracted links
            - page_content: cleaned text content
            - contains_charges: bool if charge keywords found

        Raises
        ------
        NetworkError
            If webpage fetching fails
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            if BeautifulSoup is None:
                logger.warning("BeautifulSoup not installed, cannot analyze webpage")
                raise NetworkError("BeautifulSoup not available")

            soup = BeautifulSoup(response.text, "html.parser")

            return {
                "html_text": response.text,
                "soup": soup,
                "links": self._extract_links(soup, url),
                "page_content": soup.get_text(),
                "contains_charges": self._check_charges_on_page(soup),
            }

        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Failed to fetch webpage: {str(e)}") from e

    def _extract_links(self, soup, base_url):
        """Extract all relevant links from the webpage.

        Parameters
        ----------
        soup : BeautifulSoup
            Parsed HTML document
        base_url : str
            Base URL for resolving relative links

        Returns
        -------
        list of dict
            List of dictionaries containing link information with keys:
            - url: full URL of the link
            - text: link text content
            - title: link title attribute
        """
        links = []
        for link in soup.find_all(["a", "link"], href=True):
            href = link.get("href")
            if href:
                full_url = urljoin(base_url, href)
                link_text = link.get_text(strip=True) if hasattr(link, "get_text") else ""
                links.append(
                    {
                        "url": full_url,
                        "text": link_text,
                        "title": link.get("title", ""),
                    }
                )
        return links

    def _check_charges_on_page(self, soup):
        """Check if charges are displayed directly on the page.

        Parameters
        ----------
        soup : BeautifulSoup
            Parsed HTML document to search

        Returns
        -------
        bool
            True if charge-related keywords found on page, False otherwise
        """
        page_content = soup.get_text().lower()
        charge_terms = [
            "schedule of charges",
            "fee schedule",
            "credit card fees",
            "annual fee",
            "interest rate",
            "processing fee",
        ]
        return any(term in page_content for term in charge_terms)

    def _analyze_webpage_content(self, content_data, base_url):
        """Analyze webpage content using AI.

        Parameters
        ----------
        content_data : dict
            Dictionary containing webpage content and metadata
        base_url : str
            Base URL being analyzed

        Returns
        -------
        dict
            Analysis results containing AI response and metadata
        """
        if not self._is_ai_available():
            return {
                "found": False,
                "method": "ai_analysis",
                "error": "AI analysis not available",
            }

        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")

            prompt = self._build_url_finding_prompt(
                base_url, content_data["links"][:50], content_data["contains_charges"]
            )

            ai_response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=1000,
                ),
            )

            return {
                "ai_response": ai_response.text.strip(),
                "links_analyzed": len(content_data["links"]),
                "contains_charges": content_data["contains_charges"],
            }

        except Exception as e:
            logger.error(f"AI analysis failed: {str(e)}")
            return {
                "found": False,
                "method": "ai_analysis",
                "error": f"AI analysis failed: {str(e)}",
            }

    def _process_ai_analysis(self, analysis_data, base_url):
        """Process AI analysis results.

        Parameters
        ----------
        analysis_data : dict
            AI analysis results to process
        base_url : str
            Base URL for result context

        Returns
        -------
        dict
            Final processed result with found URLs and metadata
        """
        if "ai_response" not in analysis_data:
            return analysis_data

        response_text = analysis_data["ai_response"]

        # Parse AI response
        if response_text and response_text.lower() != "none":
            # Clean up markdown if present
            if response_text.startswith("```"):
                response_text = response_text.replace("```", "").strip()

            # Check if AI suggests the current page has the charges
            if response_text.lower() == "current_page" or response_text == base_url:
                return {
                    "found": True,
                    "url": base_url,
                    "method": "ai_analysis",
                    "content_type": "WEBPAGE",
                    "links_analyzed": analysis_data.get("links_analyzed", 0),
                    "note": "Charges displayed directly on the webpage",
                }
            # Check if AI found a specific URL
            elif response_text.startswith("http"):
                # Determine content type based on URL
                content_type = (
                    "PDF" if response_text.lower().endswith(".pdf") else "WEBPAGE"
                )
                return {
                    "found": True,
                    "url": response_text,
                    "method": "ai_analysis",
                    "content_type": content_type,
                    "links_analyzed": analysis_data.get("links_analyzed", 0),
                }

        return {
            "found": False,
            "method": "ai_analysis",
            "error": "No schedule charge URL found",
        }

    def _is_ai_available(self):
        """Check if AI analysis is available.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            True if Gemini AI is properly configured and available
        """
        return (
            genai is not None
            and hasattr(settings, "GEMINI_API_KEY")
            and settings.GEMINI_API_KEY
        )

    def _build_url_finding_prompt(self, base_url, links, contains_charges):
        """Build prompt for AI to find schedule charge URL.

        Parameters
        ----------
        base_url : str
            Base URL being analyzed
        links : list of dict
            Available links extracted from the webpage
        contains_charges : bool
            Whether the current page contains charge information

        Returns
        -------
        str
            Formatted prompt for AI analysis
        """
        links_text = "\n".join(
            [
                f"URL: {link['url']}\nText: {link['text']}\nTitle: {link['title']}"
                for link in links
                if link["url"] and (link["text"] or link["title"])
            ]
        )

        charges_note = ""
        if contains_charges:
            charges_note = "\nNOTE: The current page appears to contain fee/charge information directly."

        return f"""
Analyze the following links from a bank website ({base_url}) and identify where credit card schedule of charges/fee information can be found.

Look for:
1. Links to PDF documents with terms like: "schedule of charges", "fee schedule", "credit card fees", "tariff guide", "pricing guide"
2. Links to webpages that might contain fee information
3. If the current page already displays the charges/fees directly

{charges_note}

Available links:
{links_text}

Return ONE of the following:
- If charges are displayed on the current page, return: "current_page"
- If you find a specific document/page URL, return the complete URL
- If no suitable link is found, return: "none"

Do not include any explanation, just return the URL, "current_page", or "none".
"""
