"""Pluggable storage layer for events and causal edges."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import CausalEdge, Event, EventKind, EventStatus, RelationshipType


class StorageBackend(Protocol):
    def save_event(self, event: Event) -> None: ...

    def get_event(self, event_id: str) -> Event | None: ...

    def events_for_trace(self, trace_id: str) -> list[Event]: ...

    def all_events(self) -> list[Event]: ...

    def save_edge(self, edge: CausalEdge) -> None: ...

    def edges_into(self, child_id: str) -> list[CausalEdge]: ...

    def edges_from(self, parent_id: str) -> list[CausalEdge]: ...

    def all_edges(self) -> list[CausalEdge]: ...

    def close(self) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    child_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_parent ON edges(parent_id);
CREATE INDEX IF NOT EXISTS idx_edges_child ON edges(child_id);
"""


class SQLiteStorage:
    def __init__(self, path: str | Path = "causality_graph.db") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def save_event(self, event: Event) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO events (id, trace_id, payload) VALUES (?, ?, ?)",
            (event.id, event.trace_id, event.model_dump_json()),
        )
        self._conn.commit()

    def get_event(self, event_id: str) -> Event | None:
        row = self._conn.execute("SELECT payload FROM events WHERE id = ?", (event_id,)).fetchone()
        return Event.model_validate_json(row[0]) if row else None

    def events_for_trace(self, trace_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT payload FROM events WHERE trace_id = ?", (trace_id,)
        ).fetchall()
        events = [Event.model_validate_json(r[0]) for r in rows]
        return sorted(events, key=lambda e: e.started_at)

    def all_events(self) -> list[Event]:
        rows = self._conn.execute("SELECT payload FROM events").fetchall()
        return sorted((Event.model_validate_json(r[0]) for r in rows), key=lambda e: e.started_at)

    def save_edge(self, edge: CausalEdge) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO edges (id, parent_id, child_id, payload) VALUES (?, ?, ?, ?)",
            (edge.id, edge.parent_id, edge.child_id, edge.model_dump_json()),
        )
        self._conn.commit()

    def edges_into(self, child_id: str) -> list[CausalEdge]:
        rows = self._conn.execute("SELECT payload FROM edges WHERE child_id = ?", (child_id,)).fetchall()
        return [CausalEdge.model_validate_json(r[0]) for r in rows]

    def edges_from(self, parent_id: str) -> list[CausalEdge]:
        rows = self._conn.execute("SELECT payload FROM edges WHERE parent_id = ?", (parent_id,)).fetchall()
        return [CausalEdge.model_validate_json(r[0]) for r in rows]

    def all_edges(self) -> list[CausalEdge]:
        rows = self._conn.execute("SELECT payload FROM edges").fetchall()
        return [CausalEdge.model_validate_json(r[0]) for r in rows]

    def close(self) -> None:
        self._conn.close()


class InMemoryStorage:
    def __init__(self) -> None:
        self._events: dict[str, Event] = {}
        self._edges: list[CausalEdge] = []

    def save_event(self, event: Event) -> None:
        self._events[event.id] = event

    def get_event(self, event_id: str) -> Event | None:
        return self._events.get(event_id)

    def events_for_trace(self, trace_id: str) -> list[Event]:
        return sorted((e for e in self._events.values() if e.trace_id == trace_id), key=lambda e: e.started_at)

    def all_events(self) -> list[Event]:
        return sorted(self._events.values(), key=lambda e: e.started_at)

    def save_edge(self, edge: CausalEdge) -> None:
        self._edges.append(edge)

    def edges_into(self, child_id: str) -> list[CausalEdge]:
        return [e for e in self._edges if e.child_id == child_id]

    def edges_from(self, parent_id: str) -> list[CausalEdge]:
        return [e for e in self._edges if e.parent_id == parent_id]

    def all_edges(self) -> list[CausalEdge]:
        return list(self._edges)

    def close(self) -> None:
        pass
