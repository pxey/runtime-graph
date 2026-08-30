import pytest

from causality_graph import CausalityTracer
from causality_graph.graph import CausalityGraphEngine
from causality_graph.models import RelationshipType
from causality_graph.storage import InMemoryStorage


def test_why_reconstructs_full_chain():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with tracer.trace("checkout"):
        with tracer.function("validate_cart"):
            with tracer.db_operation("orders", "INSERT"):
                outcome = tracer.outcome("order_created", status="ok")

    engine = CausalityGraphEngine(tracer.storage)
    trace = engine.why(outcome.id)
    assert trace is not None
    kinds = [step.event.kind.value for step in trace.steps]
    assert kinds == ["process", "function", "db_operation", "outcome"]


def test_why_unknown_event_returns_none():
    tracer = CausalityTracer(storage=InMemoryStorage())
    engine = CausalityGraphEngine(tracer.storage)
    assert engine.why("nonexistent") is None


def test_root_cause_candidates_finds_upstream_exception():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with pytest.raises(TimeoutError):
        with tracer.trace("checkout"):
            with tracer.function("charge_card"):
                with tracer.external_service("payment-gateway"):
                    raise TimeoutError("gateway timeout")

    events = tracer.storage.all_events()
    gateway_event = next(e for e in events if e.kind.value == "external_service")

    engine = CausalityGraphEngine(tracer.storage)
    candidates = engine.root_cause_candidates(gateway_event.id)
    assert len(candidates) >= 1
    assert any(c.event.id == gateway_event.id for c in candidates)


def test_timeline_is_chronological():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with tracer.trace("checkout") as trace_id:
        with tracer.function("step1"):
            pass
        with tracer.function("step2"):
            pass

    engine = CausalityGraphEngine(tracer.storage)
    timeline = engine.timeline(trace_id)
    timestamps = [e.started_at for e in timeline]
    assert timestamps == sorted(timestamps)
    assert len(timeline) == 3  # process + step1 + step2


def test_inferred_link_is_distinguishable_from_observed():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with tracer.trace("producer") as _:
        with tracer.queue_job("enqueue-email", job_id="job-1") as producer_event:
            pass

    with tracer.trace("consumer") as _:
        with tracer.queue_job("send-email", job_id="job-1") as consumer_event:
            pass

    tracer.link(producer_event.id, consumer_event.id, reason="shared job_id=job-1")

    # The manual link is stored alongside the automatic 'observed' edge
    # from the local trace scope, and is honestly tagged as INFERRED —
    # it was reconstructed after the fact, not directly captured.
    incoming = tracer.storage.edges_into(consumer_event.id)
    inferred_edges = [e for e in incoming if e.relationship == RelationshipType.INFERRED]
    assert len(inferred_edges) == 1
    assert inferred_edges[0].parent_id == producer_event.id
    assert "job_id=job-1" in inferred_edges[0].reason
