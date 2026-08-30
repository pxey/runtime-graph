# Runtime Causality Graph

A local-first, open-source Python library that builds a runtime execution
graph explaining **why** an observed outcome happened — by connecting
processes, functions, HTTP requests, database operations, file operations,
subprocesses, queued jobs, exceptions, and external service calls into a
single explainable causal chain.

```
Event -> Parent Event -> Child Event -> Resource -> Outcome
```

## Why

Linear logs tell you *what* happened, in order. They don't easily tell
you *why* — which upstream call actually produced this exception, which
of five candidate failures is the true root cause, or how a background
job three hops away relates to the request that triggered it.

Runtime Causality Graph builds a graph instead of a log: every unit of
execution is a node, every causal link is an edge, and edges are honestly
labeled as **observed** (captured directly from nested scopes) or
**inferred** (reconstructed after the fact, e.g. across an async or
process boundary) — with a confidence score. It does not attempt perfect
scientific causality; it gives you a ranked, explainable starting point.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.12+. The only hard runtime dependency is `pydantic`.
An optional `otel` extra is provided for teams that want to bridge into
OpenTelemetry; the core library has no such requirement.

## Quick start

```python
from causality_graph import CausalityTracer

tracer = CausalityTracer()  # defaults to a local SQLite file

with tracer.trace("checkout-request"):
    with tracer.function("validate_cart"):
        pass

    with tracer.function("charge_card"):
        try:
            with tracer.external_service("payment-gateway"):
                raise TimeoutError("gateway did not respond in 5s")
        except TimeoutError as exc:
            tracer.record_exception(exc)
            outcome = tracer.outcome("checkout_failed", status="error")
```

### Ask "why did this happen?"

```python
from causality_graph.graph import CausalityGraphEngine

engine = CausalityGraphEngine(tracer.storage)
print(engine.why(outcome.id).as_chain())
# process:checkout-request -> function:charge_card -> external_service:payment-gateway [observed] -> outcome:checkout_failed [observed]
```

### Rank root-cause candidates

```python
for candidate in engine.root_cause_candidates(outcome.id):
    print(candidate.distance, candidate.confidence, candidate.event.name)
```

### Reconstruct a timeline

```python
for event in engine.timeline(trace_id):
    print(event.started_at, event.kind, event.name, event.status)
```

### Correlate across boundaries the automatic stack can't see

```python
# In the producer process:
with tracer.queue_job("enqueue-email", job_id="job-1") as producer_event:
    ...

# Later, in a different worker process, after loading its own tracer:
with tracer.queue_job("send-email", job_id="job-1") as consumer_event:
    ...

# Explicitly, honestly labeled as inferred — not pretended to be observed:
tracer.link(producer_event.id, consumer_event.id, reason="shared job_id=job-1")
```

### CLI

```bash
causeg timeline <trace_id> --db causality_graph.db
causeg why <event_id> --db causality_graph.db
causeg root-cause <event_id> --db causality_graph.db
```

## Design principles

- **Library first, not a monitoring SaaS.** No server, no dashboard.
- **Honest about certainty.** Every edge is `observed`, `inferred`, or
  `uncertain`, with a confidence score — the library never claims
  perfect causality.
- **Event log + edges, not a single mutable graph.** Every event and edge
  is append-only, so replay and audit are free.
- **Async-safe.** The current scope stack uses `contextvars`.
- **Low-overhead instrumentation.** Context managers and a handful of
  convenience wrappers (`function`, `http_request`, `db_operation`,
  `file_operation`, `subprocess_call`, `queue_job`, `external_service`) —
  no bytecode instrumentation, no agent process.
- **Pluggable storage.** `SQLiteStorage` is the zero-config default;
  implement `StorageBackend` to plug in anything else.

## Project layout

```
src/causality_graph/
  models.py     Event, EventKind, CausalEdge, RelationshipType, CausalTrace
  collector.py  CausalityTracer — the context-manager API you use in your code
  storage.py    StorageBackend protocol + SQLiteStorage + InMemoryStorage
  graph.py      CausalityGraphEngine — why(), root_cause_candidates(), timeline()
  cli.py        `causeg` command-line tool
tests/          pytest suite
examples/       runnable example scripts
```

## Status

Alpha / MVP. Core model, collector (all event kinds from the spec),
`why()`, root-cause ranking, timeline reconstruction, explicit
observed/inferred correlation, and SQLite storage are implemented and
tested. Not yet implemented: an OpenTelemetry exporter/importer bridge and
a dashboard (intentionally out of scope for the MVP).

## License

MIT
