"""Unit tests for REPL session management."""

import time

import pytest

from cideldill_server.breakpoint_manager import BreakpointManager


def _pause_call_data(pid: int = 1234) -> dict[str, object]:
    return {
        "method_name": "demo",
        "call_id": "call-1",
        "call_site": {"stack_trace": []},
        "process_pid": pid,
        "process_start_time": 1000.0,
        "process_key": f"1000.000000+{pid}",
    }


def test_start_session_creates_session() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution(_pause_call_data())

    session_id = manager.start_repl_session(pause_id)
    session = manager.get_repl_session(session_id)

    assert session is not None
    assert session["pause_id"] == pause_id
    assert session["pid"] == 1234
    assert session["closed_at"] is None
    assert session["function_name"] == "demo"


def test_start_session_requires_pause() -> None:
    manager = BreakpointManager()
    with pytest.raises(KeyError):
        manager.start_repl_session("missing")


def test_session_id_contains_pid_and_timestamp() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution(_pause_call_data(pid=999))

    session_id = manager.start_repl_session(pause_id)
    assert session_id.startswith("999-")


def test_append_transcript_records_entry() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution(_pause_call_data())
    session_id = manager.start_repl_session(pause_id)

    index = manager.append_repl_transcript(
        session_id,
        "1 + 1",
        "2",
        "",
        False,
        result_cid=None,
    )

    session = manager.get_repl_session(session_id)
    assert session["transcript"][0]["index"] == index
    assert session["transcript"][0]["input"] == "1 + 1"
    assert session["transcript"][0]["output"] == "2"
    assert session["transcript"][0]["is_error"] is False


def test_close_session_sets_closed_at_and_prevents_append() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution(_pause_call_data())
    session_id = manager.start_repl_session(pause_id)

    manager.close_repl_session(session_id)
    session = manager.get_repl_session(session_id)
    assert session["closed_at"] is not None

    with pytest.raises(RuntimeError):
        manager.append_repl_transcript(
            session_id,
            "1 + 1",
            "2",
            "",
            False,
        )


def test_resume_execution_auto_closes_sessions() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution(_pause_call_data())
    session_id = manager.start_repl_session(pause_id)

    manager.resume_execution(pause_id, {"action": "continue"})

    session = manager.get_repl_session(session_id)
    assert session["closed_at"] is not None


def test_list_sessions_filters_by_status_and_search() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution(_pause_call_data())
    session_id = manager.start_repl_session(pause_id)
    manager.append_repl_transcript(session_id, "x", "42", "", False)
    manager.close_repl_session(session_id)

    active = manager.list_repl_sessions(status="active")
    closed = manager.list_repl_sessions(status="closed")
    search = manager.list_repl_sessions(search="demo")
    transcript_search = manager.list_repl_sessions(search="42")

    assert active == []
    assert len(closed) == 1
    assert len(search) == 1
    assert len(transcript_search) == 1


def test_list_sessions_filters_by_time_range() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution(_pause_call_data())
    session_id = manager.start_repl_session(pause_id)

    session = manager.get_repl_session(session_id)
    started_at = session["started_at"]

    later = manager.list_repl_sessions(from_ts=started_at + 10)
    earlier = manager.list_repl_sessions(to_ts=started_at - 10)

    assert later == []
    assert earlier == []


def test_session_id_collision_retries() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution(_pause_call_data())

    fixed_time = time.time()
    session_id_1 = manager.start_repl_session(pause_id, now=fixed_time)
    session_id_2 = manager.start_repl_session(pause_id, now=fixed_time)

    assert session_id_1 != session_id_2
