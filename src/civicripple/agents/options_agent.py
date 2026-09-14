"""Options agent: explains deterministic outcomes and proposes bounded
human-facing options. It generates NO new operational facts — every option
describes acting on data the deterministic core already produced, and all
consequential options are explicitly marked as requiring human approval."""

from strands import Agent
from strands.models import Model

from civicripple.domain.models import (
    FeasibilityResult,
    ImpactAssessment,
    IncidentDecision,
    OptionsReport,
)

SYSTEM_PROMPT = """You explain civic disruption incidents to a food-bank coordinator.

Rules:
- Use ONLY the deterministic facts provided: affected stops, failed
  constraints, policy reason. Never invent stops, times, or causes.
- affected_stop_ids must exactly echo the impact assessment's list.
- Propose at most 3 bounded options. Every option that commits or changes
  anything must set requires_human_approval=true.
- Never propose cancelling recipients, changing venues, or sending mass
  external notifications without human approval.
- Output only the structured report."""


def build_options_agent(model: Model) -> Agent:
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        structured_output_model=OptionsReport,
        callback_handler=None,
    )


def explain_options(
    agent: Agent,
    incident_id: str,
    decision: IncidentDecision,
    impact: ImpactAssessment,
    feasibility: FeasibilityResult | None,
) -> OptionsReport:
    prompt = (
        f"Incident {incident_id} requires human judgment.\n\n"
        f"Policy decision: {decision.model_dump_json(indent=2)}\n\n"
        f"Deterministic impact: {impact.model_dump_json(indent=2)}\n\n"
        "Feasibility result (may be null when no safe candidate exists):\n"
        f"{feasibility.model_dump_json(indent=2) if feasibility else 'null'}\n\n"
        "Explain the incident and propose bounded options."
    )
    result = agent(prompt, structured_output_model=OptionsReport)
    return result.structured_output


def options_match_impact(report: OptionsReport, impact: ImpactAssessment) -> bool:
    """Deterministic guard: options may not invent or drop affected stops."""
    return report.affected_stop_ids == impact.affected_stop_ids
