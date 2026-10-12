"""Web and Browser Navigator for fetching web pages and controlling browser windows.

Supports:
1. Headless HTTP/HTTPS fetching with robust user-agent headers, redirects, and timeouts.
2. Direct integration with desktop browsers (Edge, Chrome, Brave, Firefox) via system commands.
"""

from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from relay.browser.extractor import WebExtractor, WebPageContent
from relay.diagnostics import get_logger

log = get_logger("browser.navigator")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Relay/1.0"
)


class BrowserNavigator:
    """Manages web requests and desktop browser navigation."""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: float = 10.0) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.history: list[str] = []
        self.current_page: Optional[WebPageContent] = None

    def fetch_page(self, url: str) -> WebPageContent:
        """Fetch a web page via HTTP(S) and return structured WebPageContent."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                final_url = resp.geturl()
                charset = resp.headers.get_content_charset() or "utf-8"
                raw_bytes = resp.read()
                html = raw_bytes.decode(charset, errors="replace")
                page = WebExtractor.extract(html, base_url=final_url)
                self.history.append(final_url)
                self.current_page = page
                return page
        except urllib.error.HTTPError as e:
            log.warning("HTTP error %s when fetching %s", e.code, url)
            return WebPageContent(url=url, title=f"Error {e.code}", main_text=f"Failed to load: HTTP {e.code} {e.reason}")
        except Exception as e:
            log.warning("Failed to fetch %s: %s", url, e)
            return WebPageContent(url=url, title="Network Error", main_text=f"Failed to connect to {url}: {e}")

    def open_in_system_browser(self, url: str) -> bool:
        """Launch URL in the user's default Windows desktop browser."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            os.startfile(url)
            log.info("Opened %s in system browser", url)
            return True
        except Exception as e:
            log.warning("os.startfile failed for %s: %s", url, e)
            try:
                subprocess.Popen(["cmd.exe", "/c", "start", "", url], shell=True)
                return True
            except Exception:
                return False

    def find_active_browser(self) -> Optional[Any]:
        """Check if an existing browser window (Edge, Chrome, Brave, Firefox) is foregrounded or open."""
        try:
            from relay.system import windows

            fg = windows.foreground()
            browsers = ("chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe")
            if fg and fg.app and fg.app.lower() in browsers:
                return fg
            for w in windows.list_windows():
                if w.app and w.app.lower() in browsers and not w.minimized:
                    return w
        except Exception as e:
            log.warning("Could not list browser windows: %s", e)
        return None

    def navigate_desktop_browser(self, url: str) -> bool:
        """If a desktop browser is active, focus the address bar (Ctrl+L) and navigate to URL."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        browser_win = self.find_active_browser()
        if browser_win:
            try:
                import time
                from relay.executor.input_backend import Win32InputBackend
                from relay.system import windows

                windows.switch_to(browser_win.hwnd)
                backend = Win32InputBackend()
                backend.hotkey("ctrl", "l")
                time.sleep(0.1)
                backend.type_text(url)
                backend.press("enter")
                return True
            except Exception as e:
                log.warning("Failed to navigate active browser directly: %s", e)

        return self.open_in_system_browser(url)
