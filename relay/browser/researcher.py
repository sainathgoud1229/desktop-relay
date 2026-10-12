"""Autonomous Web Researcher and Multi-Source Synthesizer.

Performs web searches, extracts result snippets and articles,
and compiles coherent, voice-friendly summaries for Relay.
Pure Python standard library with zero external dependencies.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
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
    snippet: str = ""
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
        """Search across DuckDuckGo and Wikipedia OpenSearch for reliable results."""
        results = self._search_duckduckgo_api(query, max_results)
        if not results:
            results = self._search_wikipedia(query, max_results)
        if not results:
            results = self._search_duckduckgo_html(query, max_results)
        return results[:max_results]

    def _search_duckduckgo_api(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Query DuckDuckGo Instant Answer API."""
        encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        results: list[SearchResult] = []

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": self.navigator.user_agent},
            )
            with urllib.request.urlopen(req, timeout=self.navigator.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

            abstract = data.get("AbstractText") or data.get("Abstract") or ""
            abstract_url = data.get("AbstractURL") or ""
            heading = data.get("Heading") or query

            if abstract_url and abstract:
                results.append(
                    SearchResult(
                        title=heading,
                        url=abstract_url,
                        snippet=abstract,
                        rank=1,
                    )
                )

            # Check related topics
            rank = len(results) + 1
            for topic in data.get("RelatedTopics", []):
                if isinstance(topic, dict) and "FirstURL" in topic and "Text" in topic:
                    results.append(
                        SearchResult(
                            title=topic.get("Text", "").split(" - ")[0][:60] or query,
                            url=topic["FirstURL"],
                            snippet=topic.get("Text", ""),
                            rank=rank,
                        )
                    )
                    rank += 1
                    if len(results) >= max_results:
                        break
        except Exception as e:
            log.warning("DuckDuckGo API search failed for '%s': %s", query, e)

        return results

    def _search_wikipedia(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Query Wikipedia OpenSearch API as authoritative fallback."""
        encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={encoded}&limit={max_results}&format=json"
        results: list[SearchResult] = []

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": self.navigator.user_agent},
            )
            with urllib.request.urlopen(req, timeout=self.navigator.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

            if isinstance(data, list) and len(data) >= 4:
                titles = data[1]
                snippets = data[2] if len(data) > 2 else []
                urls = data[3]
                for idx, (title, u) in enumerate(zip(titles, urls)):
                    snip = snippets[idx] if idx < len(snippets) else ""
                    results.append(
                        SearchResult(
                            title=title,
                            url=u,
                            snippet=snip,
                            rank=idx + 1,
                        )
                    )
        except Exception as e:
            log.warning("Wikipedia OpenSearch failed for '%s': %s", query, e)

        return results

    def _search_duckduckgo_html(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Query DuckDuckGo HTML endpoint as third fallback."""
        encoded = urllib.parse.quote_plus(query.strip())
        search_url = f"https://html.duckduckgo.com/html/?q={encoded}"

        page = self.navigator.fetch_page(search_url)
        results: list[SearchResult] = []
        rank = 1

        for link in page.links:
            url = link.url
            if not url or "javascript:" in url:
                continue

            if "uddg=" in url:
                match = re.search(r"uddg=([^&]+)", url)
                if match:
                    url = urllib.parse.unquote(match.group(1))

            if "duckduckgo.com" in url or "bing.com/aclick" in url or "y.js" in url:
                continue

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

        # If top result already has a snippet from the API, use it
        top_snippet = results[0].snippet if results and results[0].snippet else ""

        if results and deep:
            first_url = results[0].url
            try:
                top_page = self.navigator.fetch_page(first_url)
            except Exception as e:
                log.warning("Could not fetch top result %s: %s", first_url, e)

        # Build synthesized answer
        if top_page and top_page.main_text:
            injection_found, _ = WebSafetyGuard.check_for_injection(top_page.main_text)
            if not injection_found:
                # Pick the first substantive paragraph with over 6 words
                chosen_para = ""
                for p in top_page.paragraphs:
                    if len(p.split()) >= 6:
                        chosen_para = p
                        break
                synthesized_text = f"According to {top_page.title or results[0].title}: {chosen_para or top_snippet}"
            else:
                synthesized_text = f"Found results for '{query}', but content was flagged by safety filters."
        elif top_snippet:
            synthesized_text = f"According to {results[0].title}: {top_snippet}"
        elif results:
            titles = [r.title for r in results[:3]]
            synthesized_text = f"Found {len(results)} sources for '{query}': " + "; ".join(titles)
        else:
            synthesized_text = f"I could not find web results for '{query}'."

        spoken = WebSafetyGuard.sanitize_for_tts(synthesized_text, max_chars=350)

        return ResearchReport(
            query=query,
            results=results,
            top_page=top_page,
            synthesized_answer=synthesized_text,
            spoken_summary=spoken,
        )
