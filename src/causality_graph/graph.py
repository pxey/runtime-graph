"""Graph engine: read-side queries over the causality graph.

    graph.why(event_id)               -> CausalTrace from root to this event
    graph.root_cause_candidates(id)   -> ranked list of upstream error events
    graph.timeline(trace_id)          -> chronological reconstruction
    graph.failure_propagation(id)     -> everything downstream that failed after this event
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CausalEdge, CausalStep, CausalTrace, Event, EventStatus
from .storage import StorageBackend


@dataclass
class RootCauseCandidate:
    event: Event
    distance: int
    """Number of hops upstream from the target event."""
    confidence: float


class CausalityGraphEngine:
    def __init__(self, storage: StorageBackend) -> None:
        self.storage = storage

    # -- explainability ----------------------------------------------------------

    def why(self, event_id: str) -> CausalTrace | None:
        """Walk backward from ``event_id`` to its root, returning the full
        explainable chain — the answer to "why did this happen?".
        """
        event = self.storage.get_event(event_id)
        if event is None:
            return None

        steps: list[CausalStep] = [CausalStep(event=event, edge=None)]
        current = event
        seen = {event.id}
        while True:
            incoming = self.storage.edges_into(current.id)
            if not incoming:
                break
            # Prefer the strongest (highest-confidence) observed edge if
            # more than one parent claims this event.
            edge = max(incoming, key=lambda e: e.confidence)
            parent = self.storage.get_event(edge.parent_id)
            if parent is None or parent.id in seen:
                break
            steps.insert(0, CausalStep(event=parent, edge=edge))
            seen.add(parent.id)
            current = parent

        return CausalTrace(steps=steps)

    # -- root cause analysis ----------------------------------------------------------

    def root_cause_candidates(self, event_id: str) -> list[RootCauseCandidate]:
        """Rank upstream events that were themselves errors/exceptions as
        likely root causes of ``event_id``. The event closest to the true
        origin (earliest in the chain, still an error) ranks highest.
        """
        trace = self.why(event_id)
        if trace is None:
            return []

        candidates: list[RootCauseCandidate] = []
        chain = trace.steps
        for distance, step in enumerate(reversed(chain)):
            event = step.event
            if event.status == EventStatus.ERROR or event.exception_type is not None:
                edge_confidence = step.edge.confidence if step.edge else 1.0
                # Earlier (further upstream) failures are weighted higher —
                # they are more likely to be the true origin rather than a
                # downstream symptom.
                confidence = edge_confidence * (1.0 - 0.1 * min(distance, 5))
                candidates.append(RootCauseCandidate(event=event, distance=distance, confidence=max(confidence, 0.1)))

        candidates.sort(key=lambda c: (-c.distance, -c.confidence))
        return candidates

    def failure_propagation(self, event_id: str) -> list[Event]:
        """Everything downstream of ``event_id`` (in causal order) that
        also failed — useful for seeing the blast radius of a failure.
        """
        results: list[Event] = []
        seen: set[str] = set()

        def walk(node_id: str) -> None:
            for edge in self.storage.edges_from(node_id):
                if edge.child_id in seen:
                    continue
                seen.add(edge.child_id)
                child = self.storage.get_event(edge.child_id)
                if child is None:
                    continue
                if child.status == EventStatus.ERROR:
                    results.append(child)
                walk(child.id)

        walk(event_id)
        return results

    # -- timeline ----------------------------------------------------------

    def timeline(self, trace_id: str) -> list[Event]:
        """Chronological reconstruction of every event in a trace."""
        return self.storage.events_for_trace(trace_id)
