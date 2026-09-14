from civicripple.orchestration.watch import WatchLedger
from civicripple.services.geocode import GEOCODED_FACT, geocode_notice


def test_i5_seattle_match() -> None:
    shape = geocode_notice("Weekend closure of I-5 express lanes in Seattle")
    assert shape is not None and shape.kind == "LineString"
    assert len(shape.coordinates) >= 2


def test_sr_and_us_routes_match() -> None:
    assert geocode_notice("SR 167 expressway work in Pierce County") is not None
    assert geocode_notice("US 101 Hoh River Bridge maintenance") is not None
    assert geocode_notice("SR 20 Oak Harbor speed limits") is not None


def test_ferry_match() -> None:
    assert geocode_notice("Washington State Ferries busy Labor Day weekend") is not None


def test_unmatched_returns_none() -> None:
    assert geocode_notice("Columbia River Gorge wind advisory") is None
    assert geocode_notice("") is None


def test_fact_constant() -> None:
    assert GEOCODED_FACT == "geometry_source: geocoded_corridor"


def test_watch_item_with_real_road_gets_geocoded_and_classified() -> None:
    from civicripple.orchestration import watch as watch_mod
    from civicripple.services.audit import AuditTrail
    from civicripple.services.storage import InMemoryIncidentStore

    store, trail = InMemoryIncidentStore(), AuditTrail()
    item = watch_mod.WatchItem(
        link="https://wsdot.wa.gov/notices/i5-closure",
        title="First of two weekend-long closures of I-5 express lanes in Seattle",
        published="Thu, 03 Sep 2026 19:47:32 +0000",
        summary="The I-5 express lanes will close this weekend.",
        hash=watch_mod.item_hash("https://wsdot.wa.gov/notices/i5-closure"),
    )
    ledger = WatchLedger()
    app_shim = type(
        "S", (), {"state": type("St", (), {
            "components": type("C", (), {"store": store, "trail": trail})(),
            "watch_ledger": ledger,
        })()},
    )()
    watch_mod._run_item_graph(app_shim, item, live=False)
    record = store.get(f"watch-{item.hash}")
    assert record is not None
    assert record.map is not None and record.map.disruption_geometry is not None
    assert record.map.disruption_geometry.kind == "LineString"
