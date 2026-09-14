"""Source Watch: background ingestion of real municipal notices.

The watch loop polls a real RSS feed, dedupes items, and runs the full
Strands graph per new notice (live models when credentials allow; scripted
models on cached real data offline). Every transition is audited."""

import asyncio
import hashlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class WatchItem:
    link: str
    title: str
    published: str
    summary: str
    hash: str


def item_hash(link: str) -> str:
    return hashlib.sha256(link.encode()).hexdigest()[:16]


@dataclass
class WatchLedger:
    _entries: list = field(default_factory=list)
    _seen: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def seen(self, h: str) -> bool:
        with self._lock:
            return h in self._seen

    def mark(self, h: str, status: str, **extra) -> None:
        with self._lock:
            self._seen[h] = status
            self._entries.append(
                {
                    "hash": h,
                    "status": status,
                    "at": datetime.now(UTC).isoformat(),
                    **extra,
                }
            )

    def snapshot(self) -> list:
        with self._lock:
            return list(reversed(self._entries[-50:]))


WATCH_URL = "https://wsdot.wa.gov/rss.xml"


def _run_item_graph(app, item: WatchItem, live: bool) -> None:
    """Run the full graph on a real feed item (offline -> scripted models)."""
    from civicripple.orchestration.replay import run_replay_scenario

    ledger = app.state.watch_ledger
    ledger.mark(item.hash, "extracting", title=item.title, link=item.link)
    notice = (
        "WASHINGTON STATE DEPARTMENT OF TRANSPORTATION NOTICE\n"
        f"Source: {item.link}\n\n{item.title}\n\n{item.summary}\n"
    )
    run = run_replay_scenario(
        "no_impact",  # manifest entry supplies the plan + scripted adapters
        store=app.state.components.store if not live else None,
        trail=app.state.components.trail if not live else None,
        correlation_id=f"watch-{item.hash}",
        live=live,
        notice_text=notice,
        source_url_override=item.link,
        geocode_first=not live,  # offline watch: deterministic geocoder,
        # never the canned scenario geometry
    )
    # Live runs persist into their own DynamoDB store/trail — mirror both
    # into the app so the run viewer and audit view can show them.
    record = run.store.get(f"watch-{item.hash}")
    if live and record is not None:
        app.state.components.store.save(record)
        for event in run.trail.events_for(f"watch-{item.hash}"):
            try:
                app.state.components.trail.record(event)
            except ValueError:
                pass  # already mirrored
    if record is None:
        ledger.mark(item.hash, "failed", title=item.title)
        return
    if record.state.value == "REVIEW_REQUIRED":
        ledger.mark(item.hash, "escalated", title=item.title, link=item.link)
    else:
        classification = (
            record.decision.classification.value if record.decision else "UNKNOWN"
        )
        ledger.mark(
            item.hash, f"classified:{classification}", title=item.title, link=item.link
        )


async def watch_loop(app, poll_seconds: int, live: bool) -> None:
    from civicripple.services.civic_source import RssCivicSource

    source = RssCivicSource(url=WATCH_URL)
    ledger = app.state.watch_ledger
    while True:
        try:
            items = await asyncio.to_thread(source.fetch)
        except Exception as exc:
            ledger.mark("source", "source_error", title=str(exc)[:120])
            try:
                items = await asyncio.to_thread(source.fetch_cached)
            except Exception:
                items = []
        for item in items:
            if ledger.seen(item.hash):
                continue
            ledger.mark(item.hash, "observed", title=item.title, link=item.link)
            try:
                await asyncio.to_thread(_run_item_graph, app, item, live)
            except Exception as exc:
                import traceback as _tb

                tb = _tb.format_exc().strip().splitlines()[-3:]
                ledger.mark(item.hash, "failed", title=str(exc)[:120], tb=" | ".join(tb))
        await asyncio.sleep(poll_seconds)


def start_watch(app, poll_seconds: int, live: bool) -> None:
    """Start the background poller (called from the FastAPI lifespan)."""
    return asyncio.get_running_loop().create_task(
        watch_loop(app, poll_seconds, live)
    )
