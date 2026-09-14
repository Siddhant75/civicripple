"""Typed domain errors.

Every error raised by the deterministic core is a DomainError subclass so
callers can distinguish domain failures from infrastructure failures.
"""


class DomainError(Exception):
    """Base class for all CivicRipple domain errors."""


class UnsupportedGeometryError(DomainError):
    """A GeoShape kind cannot be converted for deterministic calculation."""


class InvalidStateTransition(DomainError):
    """An incident state transition is not allowed by the state machine."""

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid incident state transition: {current!s} -> {target!s}")
