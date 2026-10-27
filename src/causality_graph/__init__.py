"""Runtime Causality Graph.

A local-first, open-source library that builds a runtime execution graph
— Event -> Parent Event -> Child Event -> Resource -> Outcome — from
context managers wrapped around your code, so you can ask "why did this
happen?" and get a real, explainable causal chain instead of grepping
through logs.

Quick start::

    from causality_graph import CausalityTracer

    tracer = CausalityTracer()

    with tracer.trace("checkout-request"):
        with tracer.function("validate_cart"):
            pass
        try:
            with tracer.external_service("payment-gateway"):
                raise TimeoutError("gateway timeout")
        except TimeoutError as exc:
            tracer.record_exception(exc)
            tracer.outcome("checkout_failed", status="error")

Then, given the id of the failing outcome event::

    from causality_graph.graph import CausalityGraphEngine

    engine = CausalityGraphEngine(tracer.storage)
    print(engine.why(outcome_event.id).as_chain())
    for candidate in engine.root_cause_candidates(outcome_event.id):
        print(candidate.event.name, candidate.confidence)
"""

from .collector import CausalityTracer
from .graph import CausalityGraphEngine, RootCauseCandidate
from .models import (
    CausalEdge,
    CausalStep,
    CausalTrace,
    Event,
    EventKind,
    EventStatus,
    RelationshipType,
)
from .storage import InMemoryStorage, SQLiteStorage, StorageBackend

__version__ = "0.1.0"

__all__ = [
    "CausalEdge",
    "CausalStep",
    "CausalTrace",
    "CausalityGraphEngine",
    "CausalityTracer",
    "Event",
    "EventKind",
    "EventStatus",
    "InMemoryStorage",
    "RelationshipType",
    "RootCauseCandidate",
    "SQLiteStorage",
    "StorageBackend",
    "__version__",
]
