import pytest

from causality_graph import CausalityTracer, EventKind, EventStatus
from causality_graph.storage import InMemoryStorage


def test_nested_spans_record_parent_child_edges():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with (
        tracer.trace("checkout"),
        tracer.function("validate_cart") as validate_event,
        tracer.db_operation("orders", "INSERT") as db_event,
    ):
        pass

    edges = tracer.storage.all_edges()
    pairs = {(e.parent_id, e.child_id) for e in edges}
    assert (validate_event.id, db_event.id) in pairs


def test_exception_propagates_and_is_recorded():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with (
        pytest.raises(TimeoutError),
        tracer.trace("checkout"),
        tracer.external_service("payment-gateway"),
    ):
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
    with tracer.trace("checkout"), tracer.function("finalize"):
        outcome = tracer.outcome("checkout_succeeded", status="ok")

    edges_into_outcome = tracer.storage.edges_into(outcome.id)
    assert len(edges_into_outcome) == 1


def test_stack_resets_after_scope_exits():
    tracer = CausalityTracer(storage=InMemoryStorage())
    with tracer.trace("checkout"):
        pass
    assert tracer.current_event() is None


def test_context_is_isolated_between_tracer_instances():
    first_storage = InMemoryStorage()
    second_storage = InMemoryStorage()
    first = CausalityTracer(storage=first_storage)
    second = CausalityTracer(storage=second_storage)

    with first.trace("first-trace") as first_trace_id:
        with second.trace("second-trace") as second_trace_id, second.function("inner") as inner:
            pass
        with first.function("after") as after:
            pass

    first_events = first_storage.all_events()
    second_events = second_storage.all_events()
    assert {event.trace_id for event in first_events} == {first_trace_id}
    assert {event.trace_id for event in second_events} == {second_trace_id}

    second_root = next(event for event in second_events if event.kind == EventKind.PROCESS)
    assert second_root.parent_id is None
    second_event_ids = {event.id for event in second_events}
    assert all(
        edge.parent_id in second_event_ids and edge.child_id in second_event_ids
        for edge in second_storage.all_edges()
    )
    assert inner.parent_id == second_root.id
    first_root = next(event for event in first_events if event.kind == EventKind.PROCESS)
    assert after.parent_id == first_root.id


def test_standalone_spans_do_not_reuse_trace_id():
    tracer = CausalityTracer(storage=InMemoryStorage())

    with tracer.function("first") as first:
        pass
    with tracer.function("second") as second:
        pass

    assert first.trace_id != second.trace_id
    assert first.parent_id is None
    assert second.parent_id is None

