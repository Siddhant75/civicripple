import pytest
from strands import Agent

from civicripple.domain.models import LocationPoint
from civicripple.services.replay_model import ReplayModel


def test_replay_model_returns_scripted_structured_output_offline() -> None:
    scripted = LocationPoint(lat=47.6, lon=-122.4)
    agent = Agent(model=ReplayModel([scripted]), callback_handler=None)
    result = agent("extract the location", structured_output_model=LocationPoint)
    assert result.structured_output == scripted


def test_replay_model_plays_responses_in_order() -> None:
    first = LocationPoint(lat=1.0, lon=1.0)
    second = LocationPoint(lat=2.0, lon=2.0)
    agent = Agent(model=ReplayModel([first, second]), callback_handler=None)
    assert agent("one", structured_output_model=LocationPoint).structured_output == first
    assert agent("two", structured_output_model=LocationPoint).structured_output == second


def test_replay_model_serializes_datetimes() -> None:
    # Guard: scripted models containing datetimes must serialize via mode="json".
    from civicripple.domain.models import TimeWindow
    from datetime import datetime, timezone
    scripted = TimeWindow(
        start=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
        end=datetime(2026, 9, 3, 10, tzinfo=timezone.utc),
    )
    agent = Agent(model=ReplayModel([scripted]), callback_handler=None)
    result = agent("window", structured_output_model=TimeWindow)
    assert result.structured_output == scripted
