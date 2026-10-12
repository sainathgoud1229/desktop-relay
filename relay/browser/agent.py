"""Autonomous Browser Agent.

Combines semantic HTML extraction, interactive element detection,
form filling, web research, and voice narration into a unified agent loop.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Optional

from relay.browser.extractor import InteractiveElement, WebLink, WebPageContent
from relay.browser.navigator import BrowserNavigator
from relay.browser.researcher import ResearchReport, WebResearcher
from relay.browser.safety import WebSafetyGuard
from relay.diagnostics import get_logger

log = get_logger("browser.agent")


@dataclass
class BrowserAgentStep:
    step_num: int
    action: str
    target: str
    result: str
    success: bool = True


class BrowserAgent:
    """Autonomous agent for web navigation, research, form filling, and page reading."""

    def __init__(self, bus: Any = None, navigator: Optional[BrowserNavigator] = None) -> None:
        self.bus = bus
        self.navigator = navigator or BrowserNavigator()
        self.researcher = WebResearcher(navigator=self.navigator)
        self.steps: list[BrowserAgentStep] = []
        self._step_counter = 1

    @property
    def current_page(self) -> Optional[WebPageContent]:
        return self.navigator.current_page

    def navigate(self, url: str) -> str:
        """Navigate to URL, extract page content, and emit event."""
        log.info("BrowserAgent: navigating to %s", url)
        page = self.navigator.fetch_page(url)
        summary = page.spoken_summary()

        self._record_step(
            action="navigate",
            target=url,
            result=summary,
            success=not page.title.startswith("Error"),
        )

        if self.bus:
            self.bus.emit("browser.navigated", url=url, title=page.title)

        return summary

    def open_in_desktop_browser(self, url: str) -> str:
        """Open a website in the user's active desktop browser."""
        success = self.navigator.open_in_system_browser(url)
        msg = f"Opened {url} in your desktop browser." if success else f"Failed to launch browser for {url}."
        self._record_step(action="open_desktop_browser", target=url, result=msg, success=success)
        return msg

    def research(self, topic: str) -> ResearchReport:
        """Perform autonomous multi-source research on a topic."""
        log.info("BrowserAgent: researching topic '%s'", topic)
        report = self.researcher.research_topic(topic)

        self._record_step(
            action="research",
            target=topic,
            result=report.spoken_summary,
            success=bool(report.results),
        )

        if self.bus:
            self.bus.emit("browser.researched", query=topic, results_count=len(report.results))

        return report

    def read_current_page(self) -> str:
        """Return clean spoken summary of the currently loaded page."""
        if not self.current_page:
            return "No web page is currently loaded."
        return self.current_page.spoken_summary(max_words=100)

    def find_interactive_element(self, query: str) -> Optional[InteractiveElement]:
        """Find an input, button, or control by ID, name, placeholder, or aria-label."""
        if not self.current_page or not self.current_page.interactive_elements:
            return None

        q = query.strip().lower()
        # Direct matches
        for elem in self.current_page.interactive_elements:
            if q in (elem.element_id.lower(), elem.name.lower(), elem.placeholder.lower(), elem.aria_label.lower()):
                return elem

        # Fuzzy match across labels and placeholders
        candidates = []
        for elem in self.current_page.interactive_elements:
            ident = f"{elem.name} {elem.placeholder} {elem.element_id} {elem.aria_label}".lower()
            ratio = difflib.SequenceMatcher(None, q, ident).ratio()
            if ratio > 0.4:
                candidates.append((ratio, elem))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        return None

    def fill_form(self, field_mappings: dict[str, str]) -> list[str]:
        """Simulate or plan filling form fields given a dict of {field_name: value}."""
        if not self.current_page:
            return ["No page loaded to fill form on."]

        results = []
        for field_name, value in field_mappings.items():
            elem = self.find_interactive_element(field_name)
            if elem:
                elem.value = value
                msg = f"Set field '{elem.name or elem.placeholder or field_name}' to '{value}'"
                results.append(msg)
            else:
                results.append(f"Could not locate field matching '{field_name}'")

        summary = "; ".join(results)
        self._record_step(action="fill_form", target=str(list(field_mappings.keys())), result=summary)

        if self.bus:
            self.bus.emit("browser.form_filled", fields=list(field_mappings.keys()))

        return results

    def _record_step(self, action: str, target: str, result: str, success: bool = True) -> None:
        step = BrowserAgentStep(
            step_num=self._step_counter,
            action=action,
            target=target,
            result=result,
            success=success,
        )
        self.steps.append(step)
        self._step_counter += 1
