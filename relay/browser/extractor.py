"""Semantic Web Content and Interactive Element Extractor.

Pure Python stdlib (html.parser) with zero heavy external dependencies.
Extracts clean, readable content while filtering out boilerplate, navigation chrome,
cookie notices, advertisements, tracking scripts, and stylesheets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin


@dataclass
class InteractiveElement:
    tag: str
    element_id: str = ""
    name: str = ""
    input_type: str = ""
    value: str = ""
    placeholder: str = ""
    label: str = ""
    aria_label: str = ""
    is_clickable: bool = False
    ref_index: int = 0


@dataclass
class WebLink:
    text: str
    url: str
    ref_index: int = 0


@dataclass
class WebPageContent:
    url: str
    title: str = ""
    headings: list[str] = field(default_factory=list)
    main_text: str = ""
    paragraphs: list[str] = field(default_factory=list)
    links: list[WebLink] = field(default_factory=list)
    interactive_elements: list[InteractiveElement] = field(default_factory=list)

    def spoken_summary(self, max_words: int = 60) -> str:
        """Produce a crisp, voice-friendly synopsis suitable for TTS narration."""
        parts = []
        if self.title:
            parts.append(f"Page title is {self.title}.")
        if self.headings:
            parts.append(f"Main topic: {self.headings[0]}.")
        if self.paragraphs:
            # First substantive paragraph
            for p in self.paragraphs:
                cleaned = re.sub(r"\s+", " ", p).strip()
                if len(cleaned.split()) >= 8:
                    words = cleaned.split()[:max_words]
                    parts.append(" ".join(words) + ("..." if len(words) >= max_words else ""))
                    break
        return " ".join(parts) if parts else "The page loaded, but contains no substantive text."


class _HTMLSemanticParser(HTMLParser):
    """Event-driven parser that extracts document semantics, text, and inputs."""

    BLOCK_TAGS = {
        "p", "h1", "h2", "h3", "h4", "h5", "h6", "article", "section",
        "li", "div", "blockquote", "main", "header", "footer"
    }
    IGNORE_TAGS = {"script", "style", "svg", "noscript", "iframe", "canvas", "nav"}
    BOILERPLATE_PATTERNS = [
        re.compile(r"cookie|consent|privacy policy|gdpr|accept all", re.I),
        re.compile(r"subscribe to our newsletter|sign up for updates", re.I),
        re.compile(r"advertisement|sponsored|all rights reserved", re.I),
        re.compile(r"move to sidebar|jump to (?:navigation|search)|skip to (?:main )?content", re.I),
    ]

    def __init__(self, base_url: str = "") -> None:
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self.in_title = False
        self.ignore_depth = 0
        self.current_tag = ""

        self.headings: list[str] = []
        self.paragraphs: list[str] = []
        self._current_text: list[str] = []
        self.links: list[WebLink] = []
        self.interactive: list[InteractiveElement] = []

        self._active_link_href = ""
        self._active_link_text: list[str] = []
        self._ref_counter = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        self.current_tag = tag.lower()

        if self.current_tag in self.IGNORE_TAGS:
            self.ignore_depth += 1
            return

        if self.ignore_depth > 0:
            return

        if self.current_tag == "title":
            self.in_title = True
            return

        if self.current_tag == "a":
            href = attr_dict.get("href", "")
            if href and not href.startswith(("javascript:", "#", "mailto:", "tel:")):
                self._active_link_href = urljoin(self.base_url, href)
                self._active_link_text = []

        elif self.current_tag in ("input", "button", "textarea", "select"):
            itype = attr_dict.get("type", "text" if self.current_tag == "input" else self.current_tag).lower()
            if itype != "hidden":
                elem = InteractiveElement(
                    tag=self.current_tag,
                    element_id=attr_dict.get("id", ""),
                    name=attr_dict.get("name", ""),
                    input_type=itype,
                    value=attr_dict.get("value", ""),
                    placeholder=attr_dict.get("placeholder", ""),
                    aria_label=attr_dict.get("aria-label", ""),
                    is_clickable=(self.current_tag == "button" or itype in ("submit", "button", "reset")),
                    ref_index=self._ref_counter,
                )
                self._ref_counter += 1
                self.interactive.append(elem)

        if self.current_tag in self.BLOCK_TAGS:
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.IGNORE_TAGS:
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return

        if self.ignore_depth > 0:
            return

        if tag == "title":
            self.in_title = False
            return

        if tag == "a" and self._active_link_href:
            link_text = " ".join("".join(self._active_link_text).split())
            if link_text and len(link_text) > 1:
                self.links.append(
                    WebLink(
                        text=link_text,
                        url=self._active_link_href,
                        ref_index=self._ref_counter,
                    )
                )
                self._ref_counter += 1
            self._active_link_href = ""
            self._active_link_text = []

        if tag in self.BLOCK_TAGS:
            self._flush_text(is_heading=tag.startswith("h"))

    def handle_data(self, data: str) -> None:
        if self.ignore_depth > 0:
            return
        if self.in_title:
            self.title += data
            return
        if self._active_link_href:
            self._active_link_text.append(data)
        self._current_text.append(data)

    def _flush_text(self, is_heading: bool = False) -> None:
        raw = "".join(self._current_text).strip()
        self._current_text = []
        if not raw:
            return

        # Normalize whitespace
        clean = " ".join(raw.split())
        if len(clean) < 3:
            return

        # Check for boilerplate
        for pattern in self.BOILERPLATE_PATTERNS:
            if pattern.search(clean) and len(clean.split()) < 20:
                return  # Skip cookie/ad boilerplate

        if is_heading:
            if clean not in self.headings:
                self.headings.append(clean)
        else:
            if len(clean.split()) >= 4:
                self.paragraphs.append(clean)


class WebExtractor:
    """High-level semantic web page extractor."""

    @staticmethod
    def extract(html: str, base_url: str = "") -> WebPageContent:
        """Parse raw HTML and return structured WebPageContent."""
        parser = _HTMLSemanticParser(base_url=base_url)
        try:
            parser.feed(html)
            parser.close()
        except Exception:
            pass  # Resilient to malformed HTML

        title = " ".join(parser.title.split())
        main_text = "\n\n".join(parser.paragraphs)

        return WebPageContent(
            url=base_url,
            title=title,
            headings=parser.headings,
            main_text=main_text,
            paragraphs=parser.paragraphs,
            links=parser.links[:50],  # Bound to top 50 links
            interactive_elements=parser.interactive[:30],  # Bound to top 30 controls
        )
