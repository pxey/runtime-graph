"""Example: a checkout request fails because a downstream payment gateway
times out. Trace it, then ask "why did this fail?" and rank root causes.

Run:
    python examples/checkout_failure_example.py
"""

from __future__ import annotations

from causality_graph import CausalityTracer
from causality_graph.graph import CausalityGraphEngine
from causality_graph.storage import InMemoryStorage


def run_checkout(tracer: CausalityTracer):
    with tracer.trace("checkout-request") as trace_id:
        with tracer.function("validate_cart"):
            pass

        with tracer.function("charge_card"):
            try:
                with tracer.external_service("payment-gateway"):
                    raise TimeoutError("gateway did not respond in 5s")
            except TimeoutError as exc:
                tracer.record_exception(exc)
                outcome = tracer.outcome("checkout_failed", status="error", reason="payment_timeout")
    return trace_id, outcome


def main() -> None:
    tracer = CausalityTracer(storage=InMemoryStorage())
    trace_id, outcome = run_checkout(tracer)

    engine = CausalityGraphEngine(tracer.storage)

    print("== Timeline ==")
    for event in engine.timeline(trace_id):
        duration = f"{event.duration_ms:.1f}ms" if event.duration_ms is not None else "-"
        print(f"  [{event.kind.value}] {event.name} ({event.status.value}, {duration})")

    print("\n== Why did checkout_failed happen? ==")
    print(engine.why(outcome.id).as_chain())

    print("\n== Root cause candidates ==")
    for candidate in engine.root_cause_candidates(outcome.id):
        print(f"  distance={candidate.distance} confidence={candidate.confidence:.2f} "
              f"-> {candidate.event.kind.value}:{candidate.event.name}")


if __name__ == "__main__":
    main()
