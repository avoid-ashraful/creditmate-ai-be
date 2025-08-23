"""
Enhanced schedule charge URL finder using the new LLM orchestrator.

This module provides improved URL discovery capabilities using the
LLM orchestrator with automatic fallback and better error handling.
"""

import json
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from banks.exceptions import NetworkError
from common.llm import LLMOrchestrator
from common.llm.exceptions import AllLLMProvidersFailedError

logger = logging.getLogger(__name__)


class ScheduleChargeURLFinder:
    """Enhanced schedule charge URL finder with orchestrator-based LLM analysis.

    This service provides improved URL discovery with automatic LLM provider
    fallback, better error handling, and comprehensive content analysis.
    """

    def __init__(self):
        """Initialize the schedule charge finder."""
        self.orchestrator = LLMOrchestrator()
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )

    def find_schedule_charge_url(self, base_url):
        """Find schedule of charges URL using LLM analysis with orchestrator fallback.

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
            - provider_used: str name of LLM provider used
            - error: str with error message if failed
        """
        try:
            logger.info(f"Schedule charge URL discovery for: {base_url}")

            # Check if LLM orchestrator is available
            if not self.orchestrator.is_any_provider_available():
                logger.warning("No LLM providers available, using fallback method")
                return self._fallback_pattern_search(base_url)

            # Fetch and analyze webpage content
            content_data = self._fetch_webpage_content(base_url)
            result = self._analyze_with_llm(content_data, base_url)

            return result

        except NetworkError as e:
            logger.error(f"Network error in schedule charge URL discovery: {e}")
            return {"found": False, "method": "error", "error": str(e)}
        except Exception as e:
            logger.error(f"Error in schedule charge URL discovery: {e}")
            return {"found": False, "method": "error", "error": str(e)}

    def _fetch_webpage_content(self, url):
        """Fetch and parse webpage content with enhanced error handling.

        Parameters
        ----------
        url : str
            URL to fetch and parse

        Returns
        -------
        dict
            Dictionary containing webpage content and metadata

        Raises
        ------
        NetworkError
            If webpage fetching fails
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Extract links with better filtering
            links = []
            for link in soup.find_all("a", href=True):
                href = link.get("href", "").strip()
                text = link.get_text(strip=True)

                if href and text:
                    # Convert relative URLs to absolute
                    full_url = (
                        urljoin(url, href)
                        if not href.startswith(("http://", "https://"))
                        else href
                    )

                    links.append({"url": full_url, "text": text, "href": href})

            # Extract page text content
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "header", "footer"]):
                script.decompose()

            page_text = soup.get_text(separator=" ", strip=True)

            # Check for charge-related keywords in content
            charge_keywords = [
                "schedule of charges",
                "fee schedule",
                "pricing",
                "rates and fees",
                "charges",
                "fees",
                "tariff",
                "service charges",
                "cost",
            ]

            contains_charges = any(
                keyword in page_text.lower() for keyword in charge_keywords
            )

            return {
                "html_text": response.text[:10000],  # Limit HTML size
                "soup": soup,
                "links": links[:50],  # Limit number of links
                "page_content": page_text[:5000],  # Limit text content
                "contains_charges": contains_charges,
                "base_url": url,
            }

        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Failed to fetch webpage: {e}") from e

    def _analyze_with_llm(self, content_data, base_url):
        """Analyze webpage content using LLM orchestrator.

        Parameters
        ----------
        content_data : dict
            Webpage content data
        base_url : str
            Base URL being analyzed

        Returns
        -------
        dict
            Analysis result with URL discovery information
        """
        try:
            # Build analysis prompt
            prompt = self._build_url_finding_prompt(
                base_url, content_data["links"], content_data["contains_charges"]
            )

            # Use orchestrator to analyze content
            result = self.orchestrator.generate_response(
                prompt=prompt, max_retries=1, temperature=0.1, max_tokens=1000
            )

            raw_response = result["response"]
            provider_used = result["provider"]

            # Parse LLM response
            analysis_result = self._parse_llm_response(raw_response)
            analysis_result["provider_used"] = provider_used

            if analysis_result.get("found") and analysis_result.get("url"):
                logger.info(f"URL found using {provider_used}: {analysis_result['url']}")
                return analysis_result
            else:
                logger.warning(f"No URL found by {provider_used}, trying fallback")
                return self._fallback_pattern_search(base_url)

        except AllLLMProvidersFailedError as e:
            logger.error(f"All LLM providers failed for URL analysis: {e}")
            return self._fallback_pattern_search(base_url)

        except Exception as e:
            logger.error(f"Unexpected error in LLM analysis: {e}")
            return self._fallback_pattern_search(base_url)

    def _parse_llm_response(self, raw_response):
        """Parse LLM response for URL discovery.

        Parameters
        ----------
        raw_response : str
            Raw response from LLM

        Returns
        -------
        dict
            Parsed response with URL information
        """
        try:
            # Try to parse as JSON first
            if raw_response.strip().startswith("{"):
                return json.loads(raw_response.strip())

            # Fallback: extract URL from text response
            import re

            url_pattern = r"https?://[^\\s]+"
            urls = re.findall(url_pattern, raw_response)

            if urls:
                return {
                    "found": True,
                    "url": urls[0],
                    "method": "llm_text_extraction",
                    "content_type": "PDF" if urls[0].endswith(".pdf") else "WEBPAGE",
                }

            return {
                "found": False,
                "method": "llm_analysis",
                "error": "No URL found in LLM response",
            }

        except json.JSONDecodeError:
            return {
                "found": False,
                "method": "llm_analysis",
                "error": "Failed to parse LLM response",
            }

    def _fallback_pattern_search(self, base_url):
        """Fallback method using pattern matching when LLM is not available.

        Parameters
        ----------
        base_url : str
            Base URL to search

        Returns
        -------
        dict
            Pattern search result
        """
        try:
            content_data = self._fetch_webpage_content(base_url)

            # Search for common patterns in links
            charge_patterns = [
                r"schedule.*charge",
                r"fee.*schedule",
                r"charges.*fee",
                r"pricing",
                r"tariff",
                r"service.*charge",
            ]

            for link in content_data["links"]:
                link_text = link["text"].lower()
                link_url = link["url"].lower()

                for pattern in charge_patterns:
                    import re

                    if re.search(pattern, link_text) or re.search(pattern, link_url):
                        return {
                            "found": True,
                            "url": link["url"],
                            "method": "pattern_matching",
                            "content_type": (
                                "PDF" if link["url"].endswith(".pdf") else "WEBPAGE"
                            ),
                            "pattern": pattern,
                        }

            return {
                "found": False,
                "method": "pattern_matching",
                "error": "No matching patterns found",
            }

        except Exception as e:
            return {"found": False, "method": "pattern_matching", "error": str(e)}

    def _build_url_finding_prompt(self, base_url, links, contains_charges):
        """Build prompt for LLM to find schedule charge URLs.

        Parameters
        ----------
        base_url : str
            Base URL being analyzed
        links : list
            List of links found on the page
        contains_charges : bool
            Whether page content mentions charges/fees

        Returns
        -------
        str
            Formatted prompt for LLM analysis
        """
        links_text = "\\n".join(
            [
                f"- {link['text']}: {link['url']}"
                for link in links[:20]  # Limit to first 20 links
            ]
        )

        return f"""
You are a web analysis AI. Find the schedule of charges or fee document URL from this bank website.

TASK: Analyze the links below and identify the most likely URL for schedule of charges, fee schedule, or pricing document.

WEBSITE: {base_url}
PAGE CONTAINS CHARGE INFO: {contains_charges}

LINKS FOUND:
{links_text}

INSTRUCTIONS:
1. Look for links containing terms like: "schedule of charges", "fee schedule", "pricing", "rates and fees", "tariff", "charges", "fees"
2. Prefer PDF documents over web pages when available
3. Prefer official/formal fee documents over general information pages

RESPONSE FORMAT (JSON only):
{{
    "found": true/false,
    "url": "full_url_if_found",
    "method": "llm_analysis",
    "content_type": "PDF" or "WEBPAGE",
    "confidence": "high/medium/low",
    "reasoning": "brief explanation"
}}

If no suitable URL found, return: {{"found": false, "method": "llm_analysis", "error": "No schedule of charges URL found"}}
"""

    def get_orchestrator_status(self):
        """Get the current status of the LLM orchestrator.

        Returns
        -------
        dict
            Status information about available providers
        """
        return self.orchestrator.validate_configuration()

    def test_llm_connectivity(self):
        """Test connectivity to LLM providers for URL finding.

        Returns
        -------
        dict
            Test results for each provider
        """
        test_prompt = (
            "Find a URL from this list: https://example.com/fees.pdf - Example Bank Fees"
        )
        results = {}

        for provider_name in self.orchestrator.providers:
            try:
                result = self.orchestrator.generate_response(
                    prompt=test_prompt, preferred_provider=provider_name, max_retries=0
                )
                results[provider_name] = {
                    "status": "success",
                    "response": result["response"][:100],
                }
            except Exception as e:
                results[provider_name] = {"status": "failed", "error": str(e)}

        return results
