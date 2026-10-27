"""Collector: the primary developer-facing API.

Automatic correlation (``observed`` edges) comes from nesting scopes:

    tracer = CausalityTracer()

    with tracer.trace("checkout-request") as trace_id:
        with tracer.function("validate_cart"):
            ...
        with tracer.db_operation("orders", "INSERT"):
            ...
        try:
            with tracer.external_service("payment-gateway"):
                raise TimeoutError("gateway timeout")
        except TimeoutError as exc:
            tracer.record_exception(exc)

Async boundaries the automatic stack can't see (a background worker that
picks up a job minutes later, in a different process) are linked
explicitly and honestly as ``inferred`` via :meth:`CausalityTracer.link`.
"""

from __future__ import annotations

import contextlib
import contextvars
import uuid
from typing import Any, Iterator

from .models import CausalEdge, Event, EventKind, EventStatus, RelationshipType
from .storage import SQLiteStorage, StorageBackend

def _new_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex[:12]}"


class CausalityTracer:
    """Entry point for recording and querying the runtime causality graph."""

    def __init__(self, storage: StorageBackend | None = None) -> None:
        self.storage: StorageBackend = storage if storage is not None else SQLiteStorage()
        # Keep trace context per tracer so nested tracer instances cannot create
        # cross-storage parent edges or leak trace IDs into unrelated spans.
        self._stack: contextvars.ContextVar[tuple[Event, ...]] = contextvars.ContextVar(
            f"causality_stack_{id(self)}", default=()
        )
        self._trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            f"causality_trace_id_{id(self)}", default=None
        )

    # -- trace scope ----------------------------------------------------------

    @contextlib.contextmanager
    def trace(self, name: str, trace_id: str | None = None) -> Iterator[str]:
        """Open a new top-level trace. Everything recorded inside this
        scope (including in nested async tasks that don't override the
        trace id) shares the same ``trace_id``.
        """
        tid = trace_id or _new_trace_id()
        token_trace = self._trace_id.set(tid)
        try:
            with self._span(EventKind.PROCESS, name):
                yield tid
        finally:
            self._trace_id.reset(token_trace)

    # -- internal ----------------------------------------------------------

    def _current_parent(self) -> Event | None:
        stack = self._stack.get()
        return stack[-1] if stack else None

    @contextlib.contextmanager
    def _span(
        self,
        kind: EventKind,
        name: str,
        resource: str | None = None,
        **attributes: Any,
    ) -> Iterator[Event]:
        token_trace = None
        tid = self._trace_id.get()
        if tid is None:
            tid = _new_trace_id()
            token_trace = self._trace_id.set(tid)

        try:
            parent = self._current_parent()
            event = Event(
                kind=kind,
                name=name,
                trace_id=tid,
                parent_id=parent.id if parent else None,
                resource=resource,
                attributes=attributes,
            )
            self.storage.save_event(event)
            if parent is not None:
                self.storage.save_edge(
                    CausalEdge(
                        parent_id=parent.id,
                        child_id=event.id,
                        relationship=RelationshipType.OBSERVED,
                        confidence=1.0,
                        reason="nested execution scope",
                    )
                )

            token = self._stack.set(self._stack.get() + (event,))
            status = EventStatus.OK
            try:
                yield event
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                status = EventStatus.ERROR
                self._record_exception_for(event, exc)
                raise
            finally:
                self._stack.reset(token)
                finished = event.model_copy(update={"ended_at": _now(), "status": status})
                self.storage.save_event(finished)
        finally:
            if token_trace is not None:
                self._trace_id.reset(token_trace)

    def _record_exception_for(self, parent_event: Event, exc: BaseException) -> Event:
        exc_event = Event(
            kind=EventKind.EXCEPTION,
            name=type(exc).__name__,
            trace_id=parent_event.trace_id,
            parent_id=parent_event.id,
            status=EventStatus.ERROR,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
        )
        exc_event = exc_event.model_copy(update={"ended_at": exc_event.started_at})
        self.storage.save_event(exc_event)
        self.storage.save_edge(
            CausalEdge(
                parent_id=parent_event.id,
                child_id=exc_event.id,
                relationship=RelationshipType.OBSERVED,
                confidence=1.0,
                reason="exception raised inside this scope",
            )
        )
        return exc_event

    # -- public span types ----------------------------------------------------------

    def function(self, name: str, **attrs: Any):
        return self._span(EventKind.FUNCTION, name, **attrs)

    def http_request(self, url: str, method: str = "GET", **attrs: Any):
        return self._span(EventKind.HTTP_REQUEST, f"{method} {url}", resource=url, method=method, **attrs)

    def db_operation(self, table: str, operation: str = "QUERY", **attrs: Any):
        return self._span(EventKind.DB_OPERATION, f"{operation} {table}", resource=table, operation=operation, **attrs)

    def file_operation(self, path: str, operation: str = "read", **attrs: Any):
        return self._span(EventKind.FILE_OPERATION, f"{operation} {path}", resource=path, operation=operation, **attrs)

    def subprocess_call(self, command: str, **attrs: Any):
        return self._span(EventKind.SUBPROCESS, command, resource=command, **attrs)

    def queue_job(self, job_name: str, job_id: str | None = None, **attrs: Any):
        return self._span(EventKind.QUEUE_JOB, job_name, resource=job_id, job_id=job_id, **attrs)

    def external_service(self, name: str, **attrs: Any):
        return self._span(EventKind.EXTERNAL_SERVICE, name, resource=name, **attrs)

    def task(self, name: str, **attrs: Any):
        return self._span(EventKind.TASK, name, **attrs)

    def custom(self, kind: EventKind, name: str, resource: str | None = None, **attrs: Any):
        return self._span(kind, name, resource=resource, **attrs)

    def outcome(self, name: str, status: EventStatus | str = EventStatus.OK, **attrs: Any) -> Event:
        """Record a terminal Outcome node — the "final result" the whole
        chain produced. Unlike the other span types, this is not a
        context manager: an outcome is a leaf, not a scope."""
        if isinstance(status, str):
            status = EventStatus(status)
        parent = self._current_parent()
        tid = self._trace_id.get() or _new_trace_id()
        event = Event(
            kind=EventKind.OUTCOME,
            name=name,
            trace_id=tid,
            parent_id=parent.id if parent else None,
            status=status,
            attributes=attrs,
            ended_at=_now(),
        )
        self.storage.save_event(event)
        if parent is not None:
            self.storage.save_edge(
                CausalEdge(parent_id=parent.id, child_id=event.id, relationship=RelationshipType.OBSERVED)
            )
        return event

    def record_exception(self, exc: BaseException) -> Event | None:
        """Manually attach an exception to the currently open scope,
        without letting it propagate (use this in an ``except`` block)."""
        parent = self._current_parent()
        if parent is None:
            return None
        return self._record_exception_for(parent, exc)

    # -- explicit / inferred correlation ----------------------------------------------------------

    def link(
        self,
        parent_id: str,
        child_id: str,
        relationship: RelationshipType = RelationshipType.INFERRED,
        confidence: float = 0.5,
        reason: str = "",
    ) -> CausalEdge:
        """Manually record a causal edge the automatic stack couldn't see
        — e.g. correlating a queue producer event with the consumer event
        that later processed the same job id, possibly in another
        process. Defaults to ``INFERRED`` since this is reconstructed
        after the fact, not directly observed.
        """
        edge = CausalEdge(parent_id=parent_id, child_id=child_id, relationship=relationship, confidence=confidence, reason=reason)
        self.storage.save_edge(edge)
        return edge

    def current_event(self) -> Event | None:
        return self._current_parent()

    def close(self) -> None:
        self.storage.close()


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
