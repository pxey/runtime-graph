import pytest

from causality_graph import CausalityTracer, EventKind, EventStatus
from causality_graph.storage import InMemoryStorage


def test_nested_spans_record_parent_child_edges():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with tracer.trace("checkout"):
        with tracer.function("validate_cart") as validate_event:
            with tracer.db_operation("orders", "INSERT") as db_event:
                pass

    edges = tracer.storage.all_edges()
    pairs = {(e.parent_id, e.child_id) for e in edges}
    assert (validate_event.id, db_event.id) in pairs


def test_exception_propagates_and_is_recorded():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with pytest.raises(TimeoutError):
        with tracer.trace("checkout"):
            with tracer.external_service("payment-gateway"):
                raise TimeoutError("gateway timeout")

    events = tracer.storage.all_events()
    exc_events = [e for e in events if e.kind == EventKind.EXCEPTION]
    assert len(exc_events) == 1
    assert exc_events[0].exception_type == "TimeoutError"

    gateway_event = next(e for e in events if e.kind == EventKind.EXTERNAL_SERVICE)
    assert gateway_event.status == EventStatus.ERROR


def test_record_exception_without_propagating():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with tracer.trace("checkout"):
        try:
            with tracer.external_service("payment-gateway"):
                raise TimeoutError("gateway timeout")
        except TimeoutError as exc:
            tracer.record_exception(exc)
            outcome = tracer.outcome("checkout_failed", status="error")

    assert outcome.status == EventStatus.ERROR
    events = tracer.storage.all_events()
    exc_events = [e for e in events if e.kind == EventKind.EXCEPTION]
    assert len(exc_events) == 1


def test_outcome_links_to_current_parent():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with tracer.trace("checkout"):
        with tracer.function("finalize"):
            outcome = tracer.outcome("checkout_succeeded", status="ok")

    edges_into_outcome = tracer.storage.edges_into(outcome.id)
    assert len(edges_into_outcome) == 1


def test_stack_resets_after_scope_exits():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with tracer.trace("checkout"):
        pass
    assert tracer.current_event() is None
