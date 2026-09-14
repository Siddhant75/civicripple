from pathlib import Path

from civicripple.services.civic_source import RssCivicSource
from civicripple.orchestration.watch import WatchLedger

FEED = Path("src/civicripple/fixtures/notices_src/sample_feed.xml")


def test_rss_source_parses_real_feed_copy() -> None:
    source = RssCivicSource(url="file://" + str(FEED))
    items = source.fetch()
    assert len(items) >= 5
    assert all(i.hash and i.link.startswith("http") for i in items)
    assert any(
        "closure" in i.title.lower() or "traffic" in i.title.lower() for i in items
    )


def test_ledger_dedupes_by_hash() -> None:
    ledger = WatchLedger()
    assert ledger.seen("abc") is False
    ledger.mark("abc", "observed")
    assert ledger.seen("abc") is True
    ledger.mark("abc", "classified:NO_IMPACT")
    snap = ledger.snapshot()
    assert snap[0]["status"] == "classified:NO_IMPACT"  # newest first


def test_ledger_snapshot_newest_first_capped() -> None:
    ledger = WatchLedger()
    for i in range(60):
        ledger.mark(f"h{i:03d}", "observed")
    snap = ledger.snapshot()
    assert len(snap) == 50
    assert snap[0]["hash"] == "h059"  # newest first


def test_watch_item_runs_graph_end_to_end() -> None:
    from civicripple.services.audit import AuditTrail
    from civicripple.services.storage import InMemoryIncidentStore
    from civicripple.orchestration import watch as watch_mod

    store, trail = InMemoryIncidentStore(), AuditTrail()
    item = watch_mod.WatchItem(
        link="https://wsdot.wa.gov/notices/test-item",
        title="Weekend closure of I-5 express lanes in Seattle",
        published="Thu, 10 Sep 2026 19:47:32 +0000",
        summary="The I-5 express lanes will close.",
        hash=watch_mod.item_hash("https://wsdot.wa.gov/notices/test-item"),
    )
    ledger = WatchLedger()
    app_shim = type(
        "S",
        (),
        {
            "state": type(
                "St",
                (),
                {
                    "components": type("C", (), {"store": store, "trail": trail})(),
                    "watch_ledger": ledger,
                },
            )()
        },
    )()
    watch_mod._run_item_graph(app_shim, item, live=False)
    record = store.get(f"watch-{item.hash}")
    assert record is not None
    assert record.state.value in ("REVIEW_REQUIRED", "RESOLVED")
    statuses = [e["status"] for e in ledger.snapshot()]
    assert "observed" in statuses or statuses  # ledger recorded marks
