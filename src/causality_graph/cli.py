"""Command-line interface.

    causeg timeline <trace_id> --db causality_graph.db
    causeg why <event_id> --db causality_graph.db
    causeg root-cause <event_id> --db causality_graph.db
"""

from __future__ import annotations

import argparse
import sys

from .graph import CausalityGraphEngine
from .storage import SQLiteStorage


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="causeg", description="Inspect a Runtime Causality Graph database.")
    parser.add_argument("--db", default="causality_graph.db")
    sub = parser.add_subparsers(dest="command", required=True)

    p_timeline = sub.add_parser("timeline", help="Chronological reconstruction of a trace.")
    p_timeline.add_argument("trace_id")

    p_why = sub.add_parser("why", help="Explain the causal chain leading to an event.")
    p_why.add_argument("event_id")

    p_rc = sub.add_parser("root-cause", help="Rank upstream error candidates for an event.")
    p_rc.add_argument("event_id")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    storage = SQLiteStorage(args.db)
    engine = CausalityGraphEngine(storage)

    try:
        if args.command == "timeline":
            events = engine.timeline(args.trace_id)
            if not events:
                print(f"No events found for trace: {args.trace_id}", file=sys.stderr)
                return 1
            for e in events:
                duration = f"{e.duration_ms:.1f}ms" if e.duration_ms is not None else "in-progress"
                print(f"{e.started_at.isoformat()}  [{e.kind.value}] {e.name}  ({e.status.value}, {duration})  id={e.id}")

        elif args.command == "why":
            trace = engine.why(args.event_id)
            if trace is None:
                print(f"Event not found: {args.event_id}", file=sys.stderr)
                return 1
            print(trace.as_chain())

        elif args.command == "root-cause":
            candidates = engine.root_cause_candidates(args.event_id)
            if not candidates:
                print("No error events found upstream of this event.")
            for c in candidates:
                print(
                    f"[distance={c.distance}, confidence={c.confidence:.2f}] "
                    f"{c.event.kind.value}:{c.event.name} "
                    f"({c.event.exception_type or c.event.status.value}) id={c.event.id}"
                )

        return 0
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
