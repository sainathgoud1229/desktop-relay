"""Autonomous Web Researcher and Multi-Source Synthesizer.

Performs web searches, extracts result snippets and articles,
and compiles coherent, voice-friendly summaries for Relay.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

from relay.browser.extractor import WebExtractor, WebPageContent
from relay.browser.navigator import BrowserNavigator
from relay.browser.safety import WebSafetyGuard
from relay.diagnostics import get_logger

log = get_logger("browser.researcher")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    rank: int = 1


@dataclass
class ResearchReport:
    query: str
    results: list[SearchResult] = field(default_factory=list)
    top_page: Optional[WebPageContent] = None
    synthesized_answer: str = ""
    spoken_summary: str = ""


class WebResearcher:
    """Orchestrates web searches and multi-source synthesis."""

    def __init__(self, navigator: Optional[BrowserNavigator] = None) -> None:
        self.navigator = navigator or BrowserNavigator()

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Perform search using DuckDuckGo HTML endpoint (no API key required)."""
        encoded_query = urllib.parse.quote_plus(query.strip())
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        page = self.navigator.fetch_page(search_url)
        results: list[SearchResult] = []
        rank = 1

        # DuckDuckGo HTML puts result links with class or in specific format
        # Extract meaningful external links
        for link in page.links:
            url = link.url
            # Filter internal DuckDuckGo links
            if "duckduckgo.com" in url or "javascript:" in url:
                continue

            # Clean DuckDuckGo uddg redirect URLs if present
            if "uddg=" in url:
                match = re.search(r"uddg=([^&]+)", url)
                if match:
                    url = urllib.parse.unquote(match.group(1))

            if url.startswith(("http://", "https://")) and len(link.text.split()) >= 2:
                results.append(
                    SearchResult(
                        title=link.text,
                        url=url,
                        snippet="",
                        rank=rank,
                    )
                )
                rank += 1
                if len(results) >= max_results:
                    break

        return results

    def research_topic(self, query: str, deep: bool = True) -> ResearchReport:
        """Execute a full research cycle: search, inspect top page, synthesize answer."""
        results = self.search(query, max_results=4)
        top_page = None
        synthesized_text = ""

        if results and deep:
            # Fetch the first substantive search result
            first_url = results[0].url
            try:
                top_page = self.navigator.fetch_page(first_url)
            except Exception as e:
                log.warning("Could not fetch top result %s: %s", first_url, e)

        # Build synthesized answer
        if top_page and top_page.main_text:
            injection_found, _ = WebSafetyGuard.check_for_injection(top_page.main_text)
            if not injection_found:
                first_para = top_page.paragraphs[0] if top_page.paragraphs else ""
                synthesized_text = f"According to {top_page.title or results[0].title}: {first_para}"
            else:
                synthesized_text = f"Found results for '{query}', but content was flagged by safety filters."
        elif results:
            titles = [r.title for r in results[:3]]
            synthesized_text = f"Found {len(results)} sources for '{query}': " + "; ".join(titles)
        else:
            synthesized_text = f"I could not find web results for '{query}'."

        spoken = WebSafetyGuard.sanitize_for_tts(synthesized_text, max_chars=300)

        return ResearchReport(
            query=query,
            results=results,
            top_page=top_page,
            synthesized_answer=synthesized_text,
            spoken_summary=spoken,
        )
