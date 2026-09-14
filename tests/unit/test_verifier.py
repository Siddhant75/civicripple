from pathlib import Path

from civicripple.agents.evidence_verifier import build_verifier_agent, verify_evidence
from civicripple.domain.enums import VerificationStatus
from civicripple.domain.models import DisruptionEventCandidate, VerificationVerdict
from civicripple.services.replay_model import ReplayModel

FIXTURES = Path("src/civicripple/fixtures")


def _candidate(scenario: str) -> DisruptionEventCandidate:
    return DisruptionEventCandidate.model_validate_json(
        (FIXTURES / "model_replays" / scenario / "extractor.json").read_text()
    )


def _verdict(scenario: str) -> VerificationVerdict:
    return VerificationVerdict.model_validate_json(
        (FIXTURES / "model_replays" / scenario / "verifier.json").read_text()
    )


def test_verifier_returns_typed_verdict() -> None:
    agent = build_verifier_agent(ReplayModel([_verdict("feasible_reroute")]))
    verdict = verify_evidence(agent, _candidate("feasible_reroute"))
    assert verdict.status is VerificationStatus.VERIFIED
    assert verdict.authority == "City of Replayville"


def test_verifier_can_mark_source_unverified() -> None:
    unverified = _verdict("feasible_reroute").model_copy(
        update={"status": VerificationStatus.UNVERIFIED, "reasons": ["authority not established"]}
    )
    agent = build_verifier_agent(ReplayModel([unverified]))
    verdict = verify_evidence(agent, _candidate("feasible_reroute"))
    assert verdict.status is VerificationStatus.UNVERIFIED
