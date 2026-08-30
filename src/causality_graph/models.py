"""Core domain model for the Runtime Causality Graph.

    Event -> Parent Event -> Child Event -> Resource -> Outcome

Every unit of execution — a process, a function call, an HTTP request, a
database operation, a file operation, a subprocess, a queued job, an
exception, a call to an external service, or a final outcome — becomes an
:class:`Event`. Events are linked by :class:`CausalEdge` records that are
explicitly tagged as ``observed`` (captured directly from nested scopes),
``inferred`` (correlated after the fact, e.g. by a shared job id across an
async boundary), or ``uncertain`` (a best-effort guess) — the model never
pretends inferred causality is as solid as observed causality.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventKind(str, Enum):
    PROCESS = "process"
    TASK = "task"
    FUNCTION = "function"
    HTTP_REQUEST = "http_request"
    DB_OPERATION = "db_operation"
    FILE_OPERATION = "file_operation"
    SUBPROCESS = "subprocess"
    QUEUE_JOB = "queue_job"
    EXCEPTION = "exception"
    EXTERNAL_SERVICE = "external_service"
    OUTCOME = "outcome"
    CUSTOM = "custom"


class EventStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    UNKNOWN = "unknown"


class Event(BaseModel):
    """A single observed unit of execution."""

    id: str = Field(default_factory=lambda: _new_id("evt"))
    kind: EventKind
    name: str
    trace_id: str
    """Groups all events that belong to the same logical execution."""
    parent_id: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    status: EventStatus = EventStatus.UNKNOWN
    resource: str | None = None
    """What this event touched: a URL, a table name, a file path, a queue name..."""
    attributes: dict[str, Any] = Field(default_factory=dict)
    exception_type: str | None = None
    exception_message: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds() * 1000


class RelationshipType(str, Enum):
    OBSERVED = "observed"
    """Directly captured from nested context managers/decorators."""
    INFERRED = "inferred"
    """Reconstructed after the fact, e.g. by correlating a shared job id
    across an async or process boundary the automatic stack couldn't see."""
    UNCERTAIN = "uncertain"
    """A best-effort guess (e.g. time proximity alone) — treat with caution."""


class CausalEdge(BaseModel):
    """A directed causal link: parent_id caused/produced child_id."""

    id: str = Field(default_factory=lambda: _new_id("edge"))
    parent_id: str
    child_id: str
    relationship: RelationshipType = RelationshipType.OBSERVED
    confidence: float = 1.0
    reason: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class CausalStep(BaseModel):
    """One hop in a reconstructed causal chain, pairing an event with the
    edge that connected it to its parent (None for the root)."""

    event: Event
    edge: CausalEdge | None


class CausalTrace(BaseModel):
    """A full explainable chain from a root event down to a target event."""

    steps: list[CausalStep]

    def as_chain(self) -> str:
        parts = []
        for step in self.steps:
            marker = "" if step.edge is None else f" [{step.edge.relationship.value}]"
            parts.append(f"{step.event.kind.value}:{step.event.name}{marker}")
        return " -> ".join(parts)

    @property
    def root(self) -> Event | None:
        return self.steps[0].event if self.steps else None

    @property
    def target(self) -> Event | None:
        return self.steps[-1].event if self.steps else None
