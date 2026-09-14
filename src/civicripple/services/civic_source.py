"""Civic notice source adapters. Replay reads fixtures; the RSS source
fetches a REAL municipal feed (WSDOT) and caches raw copies as the
designed offline fallback."""

import hashlib
import ssl
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from civicripple.domain.models import OperationPlan
from civicripple.orchestration.watch import WatchItem

FIXTURES = Path(__file__).parent.parent / "fixtures"


class ReplayCivicSource:
    def __init__(
        self, plan_name: str = "operation_plan.json", notice_name: str = ""
    ) -> None:
        self._plan_path = FIXTURES / plan_name
        self._notice_path = FIXTURES / "notices_src" / notice_name

    def load_plan(self) -> OperationPlan:
        return OperationPlan.model_validate_json(self._plan_path.read_text())

    def load_notice_text(self) -> str:
        if not self._notice_path.exists():
            raise FileNotFoundError(f"notice fixture not found: {self._notice_path}")
        return self._notice_path.read_text()


def _parse_rss(raw: str) -> list[WatchItem]:
    root = ET.fromstring(raw)
    items: list[WatchItem] = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        published = (node.findtext("pubDate") or "").strip()
        summary = (node.findtext("description") or "").strip()
        if not link:
            continue
        items.append(
            WatchItem(
                link=link,
                title=title,
                published=published,
                summary=summary,
                hash=hashlib.sha256(link.encode()).hexdigest()[:16],
            )
        )
    return items


_system_ctx: ssl.SSLContext | None = None
_ctx_lock = threading.Lock()


def _system_ssl_context() -> ssl.SSLContext:
    """TLS context trusting the OS certificate store (Windows cert store
    includes the proxy CA on intercepted networks). Built once; passed
    per-request — no global ssl monkey-patching (that recurses badly in
    long-running servers)."""
    global _system_ctx
    with _ctx_lock:
        if _system_ctx is None:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_default_certs()
            _system_ctx = ctx
    return _system_ctx


class RssCivicSource:
    """Real municipal RSS feed. Cached copies power the offline demo."""

    def __init__(self, url: str = "https://wsdot.wa.gov/rss.xml") -> None:
        self._url = url
        self._cache_dir = FIXTURES / "notices_src" / "live_cache"

    def fetch(self) -> list[WatchItem]:
        if self._url.startswith("file://"):
            raw = Path(self._url[7:]).read_text(encoding="utf-8", errors="replace")
        else:
            response = httpx.get(
                self._url,
                timeout=15.0,
                follow_redirects=True,
                verify=_system_ssl_context(),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/128.0.0.0 Safari/537.36"
                    )
                },
            )
            response.raise_for_status()
            raw = response.text
        items = _parse_rss(raw)
        if items:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            (self._cache_dir / f"{items[0].hash}.xml").write_text(
                raw, encoding="utf-8"
            )
        return items

    def fetch_cached(self) -> list[WatchItem]:
        newest = None
        for path in self._cache_dir.glob("*.xml"):
            newest = path
        if newest is None:
            return []
        return _parse_rss(newest.read_text(encoding="utf-8", errors="replace"))
