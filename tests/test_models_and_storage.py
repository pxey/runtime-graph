from causality_graph.models import CausalEdge, Event, EventKind, EventStatus, RelationshipType
from causality_graph.storage import InMemoryStorage, SQLiteStorage


def test_event_duration_none_until_ended():
    event = Event(kind=EventKind.FUNCTION, name="f", trace_id="t1")
    assert event.duration_ms is None


def test_inmemory_storage_roundtrip():
    storage = InMemoryStorage()
    parent = Event(kind=EventKind.PROCESS, name="p", trace_id="t1")
    child = Event(kind=EventKind.FUNCTION, name="f", trace_id="t1", parent_id=parent.id)
    storage.save_event(parent)
    storage.save_event(child)
    edge = CausalEdge(parent_id=parent.id, child_id=child.id, relationship=RelationshipType.OBSERVED)
    storage.save_edge(edge)

    assert storage.get_event(parent.id) == parent
    assert len(storage.events_for_trace("t1")) == 2
    assert len(storage.edges_into(child.id)) == 1
    assert len(storage.edges_from(parent.id)) == 1


def test_sqlite_storage_roundtrip(tmp_path):
    db_path = tmp_path / "causeg.db"
    storage = SQLiteStorage(db_path)
    event = Event(kind=EventKind.DB_OPERATION, name="INSERT orders", trace_id="t1", status=EventStatus.OK)
    storage.save_event(event)
    storage.close()

    reopened = SQLiteStorage(db_path)
    fetched = reopened.get_event(event.id)
    assert fetched is not None
    assert fetched.name == "INSERT orders"
    assert fetched.status == EventStatus.OK
    reopened.close()
