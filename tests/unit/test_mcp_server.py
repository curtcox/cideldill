"""Unit tests for MCP server tool handlers."""

import asyncio
import hashlib
import json

import pytest

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.cid_store import CIDStore
from cideldill_server.serialization import serialize

pytest.importorskip("mcp")

from cideldill_server.mcp_server import BreakpointMCPServer  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _parse_tool_result(result):
    assert result.content is not None
    assert len(result.content) == 1
    content = result.content[0]
    assert content.type == "text"
    return json.loads(content.text)


def _parse_resource_result(result):
    contents = result.contents if hasattr(result, "contents") else result
    assert contents is not None
    assert len(contents) == 1
    content = contents[0]
    text = getattr(content, "text", None)
    if text is None:
        text = content.content
        if isinstance(text, bytes):
            text = text.decode("utf-8")
    return json.loads(text)


def test_all_tools_registered() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    tools = _run(server.list_tools())
    assert len(tools) == 14


def test_tool_names_prefixed() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    tools = _run(server.list_tools())
    assert all(tool.name.startswith("breakpoint_") for tool in tools)


def test_no_duplicate_tool_names() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    tools = _run(server.list_tools())
    names = [tool.name for tool in tools]
    assert len(names) == len(set(names))


def test_list_breakpoints_empty() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_list_breakpoints", {}))
    payload = _parse_tool_result(result)
    assert payload["breakpoints"] == []
    assert payload["behaviors"] == {}
    assert payload["after_behaviors"] == {}
    assert payload["replacements"] == {}


def test_list_breakpoints_with_entries() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("func_a")
    manager.add_breakpoint("func_b")
    manager.set_breakpoint_behavior("func_a", "stop")
    manager.set_after_breakpoint_behavior("func_b", "exception")
    manager.set_breakpoint_replacement("func_b", "func_b_alt")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_list_breakpoints", {}))
    payload = _parse_tool_result(result)

    assert set(payload["breakpoints"]) == {"func_a", "func_b"}
    assert payload["behaviors"]["func_a"] == "stop"
    assert payload["after_behaviors"]["func_b"] == "exception"
    assert payload["replacements"]["func_b"] == "func_b_alt"


def test_add_breakpoint_minimal() -> None:
    manager = BreakpointManager()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_add", {"function_name": "my_func"}))
    payload = _parse_tool_result(result)

    assert payload["status"] == "ok"
    assert manager.has_breakpoint("my_func")


def test_add_breakpoint_with_behavior() -> None:
    manager = BreakpointManager()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(server.call_tool("breakpoint_add", {"function_name": "my_func", "behavior": "stop"}))
    assert manager.get_breakpoint_behavior("my_func") == "stop"


def test_add_breakpoint_missing_function_name() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_add", {}))
    payload = _parse_tool_result(result)

    assert payload["error"] == "missing_parameter"


def test_add_breakpoint_invalid_behavior() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(
        server.call_tool(
            "breakpoint_add",
            {"function_name": "my_func", "behavior": "invalid"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "invalid_behavior"


def test_add_breakpoint_duplicate() -> None:
    manager = BreakpointManager()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(server.call_tool("breakpoint_add", {"function_name": "dup"}))
    result = _run(server.call_tool("breakpoint_add", {"function_name": "dup"}))
    payload = _parse_tool_result(result)

    assert payload["status"] == "ok"
    assert manager.has_breakpoint("dup")


def test_remove_breakpoint_exists() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("remove_me")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_remove", {"function_name": "remove_me"}))
    payload = _parse_tool_result(result)

    assert payload["status"] == "ok"
    assert not manager.has_breakpoint("remove_me")


def test_remove_breakpoint_not_found() -> None:
    manager = BreakpointManager()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_remove", {"function_name": "missing"}))
    payload = _parse_tool_result(result)

    assert payload["status"] == "ok"


def test_remove_breakpoint_clears_behavior() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("clear_me")
    manager.set_breakpoint_behavior("clear_me", "stop")
    manager.set_after_breakpoint_behavior("clear_me", "exception")
    manager.set_breakpoint_replacement("clear_me", "alt")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(server.call_tool("breakpoint_remove", {"function_name": "clear_me"}))

    assert "clear_me" not in manager.get_breakpoint_behaviors()
    assert "clear_me" not in manager.get_after_breakpoint_behaviors()
    assert "clear_me" not in manager.get_breakpoint_replacements()


def test_set_behavior_stop() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(
        server.call_tool(
            "breakpoint_set_behavior",
            {"function_name": "target", "behavior": "stop"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["behavior"] == "stop"
    assert manager.get_breakpoint_behavior("target") == "stop"


def test_set_behavior_go() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_set_behavior",
            {"function_name": "target", "behavior": "go"},
        )
    )
    assert manager.get_breakpoint_behavior("target") == "go"


def test_set_behavior_yield() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_set_behavior",
            {"function_name": "target", "behavior": "yield"},
        )
    )
    assert manager.get_breakpoint_behavior("target") == "yield"


def test_set_behavior_invalid() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(
        server.call_tool(
            "breakpoint_set_behavior",
            {"function_name": "target", "behavior": "invalid"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "invalid_behavior"


def test_set_behavior_no_breakpoint() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(
        server.call_tool(
            "breakpoint_set_behavior",
            {"function_name": "missing", "behavior": "stop"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "breakpoint_not_found"


def test_set_after_behavior_stop() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(
        server.call_tool(
            "breakpoint_set_after_behavior",
            {"function_name": "target", "behavior": "stop"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["behavior"] == "stop"


def test_set_after_behavior_go() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_set_after_behavior",
            {"function_name": "target", "behavior": "go"},
        )
    )
    assert manager.get_after_breakpoint_behavior("target") == "go"


def test_set_after_behavior_exception() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_set_after_behavior",
            {"function_name": "target", "behavior": "exception"},
        )
    )
    assert manager.get_after_breakpoint_behavior("target") == "exception"


def test_set_after_behavior_stop_exception() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_set_after_behavior",
            {"function_name": "target", "behavior": "stop_exception"},
        )
    )
    assert manager.get_after_breakpoint_behavior("target") == "stop_exception"


def test_set_after_behavior_yield() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_set_after_behavior",
            {"function_name": "target", "behavior": "yield"},
        )
    )
    assert manager.get_after_breakpoint_behavior("target") == "yield"


def test_set_after_behavior_invalid() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("target")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(
        server.call_tool(
            "breakpoint_set_after_behavior",
            {"function_name": "target", "behavior": "invalid"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "invalid_behavior"


def test_set_after_behavior_no_breakpoint() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(
        server.call_tool(
            "breakpoint_set_after_behavior",
            {"function_name": "missing", "behavior": "stop"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "breakpoint_not_found"


def test_set_replacement_valid() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("func_a")
    manager.register_function("func_a", signature="(x)")
    manager.register_function("func_b", signature="(x)")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(
        server.call_tool(
            "breakpoint_set_replacement",
            {"function_name": "func_a", "replacement_function": "func_b"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["status"] == "ok"
    assert manager.get_breakpoint_replacement("func_a") == "func_b"


def test_set_replacement_clear() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("func_a")
    manager.register_function("func_a", signature="(x)")
    manager.register_function("func_b", signature="(x)")
    manager.set_breakpoint_replacement("func_a", "func_b")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_set_replacement",
            {"function_name": "func_a", "replacement_function": ""},
        )
    )

    assert manager.get_breakpoint_replacement("func_a") is None


def test_set_replacement_signature_mismatch() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("func_a")
    manager.register_function("func_a", signature="(x)")
    manager.register_function("func_b", signature="(y)")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(
        server.call_tool(
            "breakpoint_set_replacement",
            {"function_name": "func_a", "replacement_function": "func_b"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "signature_mismatch"


def test_set_replacement_no_signatures_registered() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("func_a")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(
        server.call_tool(
            "breakpoint_set_replacement",
            {"function_name": "func_a", "replacement_function": "func_b"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "signature_mismatch"


def test_set_replacement_no_breakpoint() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(
        server.call_tool(
            "breakpoint_set_replacement",
            {"function_name": "func_a", "replacement_function": "func_b"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "breakpoint_not_found"


def test_get_default_behavior_initial() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_get_default_behavior", {}))
    payload = _parse_tool_result(result)

    assert payload["behavior"] == "stop"


def test_set_default_behavior_go() -> None:
    manager = BreakpointManager()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_set_default_behavior", {"behavior": "go"}))
    payload = _parse_tool_result(result)

    assert payload["status"] == "ok"
    assert manager.get_default_behavior() == "go"


def test_set_default_behavior_exception() -> None:
    manager = BreakpointManager()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))
    _run(server.call_tool("breakpoint_set_default_behavior", {"behavior": "exception"}))
    assert manager.get_default_behavior() == "exception"


def test_set_default_behavior_stop_exception() -> None:
    manager = BreakpointManager()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))
    _run(server.call_tool("breakpoint_set_default_behavior", {"behavior": "stop_exception"}))
    assert manager.get_default_behavior() == "stop_exception"


def test_set_default_behavior_invalid() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(
        server.call_tool(
            "breakpoint_set_default_behavior",
            {"behavior": "invalid"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "invalid_behavior"


def test_list_paused_empty() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_list_paused", {}))
    payload = _parse_tool_result(result)

    assert payload["paused"] == []


def test_list_paused_with_entries() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_list_paused", {}))
    payload = _parse_tool_result(result)

    assert payload["paused"]
    assert payload["paused"][0]["id"] == pause_id


def test_list_paused_includes_repl_sessions() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    session_id = manager.start_repl_session(pause_id)
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_list_paused", {}))
    payload = _parse_tool_result(result)

    assert session_id in payload["paused"][0]["repl_sessions"]


def test_continue_default_action() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_continue", {"pause_id": pause_id}))
    payload = _parse_tool_result(result)

    assert payload["status"] == "ok"
    assert manager.get_resume_action(pause_id)["action"] == "continue"


def test_continue_skip_with_fake_result() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(
        server.call_tool(
            "breakpoint_continue",
            {"pause_id": pause_id, "action": "skip", "fake_result": {"ok": True}},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["status"] == "ok"
    action = manager.get_resume_action(pause_id)
    assert action["action"] == "skip"
    assert action["fake_result_serialization_format"] == "json"


def test_continue_raise_exception() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_continue",
            {
                "pause_id": pause_id,
                "action": "raise",
                "exception_type": "ValueError",
                "exception_message": "boom",
            },
        )
    )

    action = manager.get_resume_action(pause_id)
    assert action["action"] == "raise"
    assert action["exception_type"] == "ValueError"
    assert action["exception_message"] == "boom"


def test_continue_with_modified_args() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_continue",
            {"pause_id": pause_id, "modified_args": [1, 2, 3]},
        )
    )
    action = manager.get_resume_action(pause_id)
    assert action["modified_args"][0]["serialization_format"] == "json"


def test_continue_with_modified_kwargs() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_continue",
            {"pause_id": pause_id, "modified_kwargs": {"x": 1}},
        )
    )
    action = manager.get_resume_action(pause_id)
    assert action["modified_kwargs"]["x"]["serialization_format"] == "json"


def test_continue_with_replacement_function() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_continue",
            {"pause_id": pause_id, "replacement_function": "alt"},
        )
    )
    action = manager.get_resume_action(pause_id)
    assert action["action"] == "replace"
    assert action["function_name"] == "alt"


def test_continue_replacement_overrides_action() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_continue",
            {"pause_id": pause_id, "action": "skip", "replacement_function": "alt"},
        )
    )
    action = manager.get_resume_action(pause_id)
    assert action["action"] == "replace"


def test_continue_invalid_pause_id() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_continue", {"pause_id": "missing"}))
    payload = _parse_tool_result(result)

    assert payload["error"] == "pause_not_found"


def test_continue_already_resumed() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    manager.resume_execution(pause_id, {"action": "continue"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_continue", {"pause_id": pause_id}))
    payload = _parse_tool_result(result)

    assert payload["error"] == "pause_already_resumed"


def test_continue_uses_json_format() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    _run(
        server.call_tool(
            "breakpoint_continue",
            {"pause_id": pause_id, "fake_result": {"ok": True}},
        )
    )
    action = manager.get_resume_action(pause_id)
    assert action["fake_result_serialization_format"] == "json"


def test_list_functions_empty() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_list_functions", {}))
    payload = _parse_tool_result(result)

    assert payload["functions"] == []
    assert payload["signatures"] == {}
    assert payload["metadata"] == {}


def test_list_functions_with_entries() -> None:
    manager = BreakpointManager()
    manager.register_function("func_a", signature="(x: int)", metadata={"foo": "bar"})
    manager.register_function("func_b", signature="(y: str)")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_list_functions", {}))
    payload = _parse_tool_result(result)

    assert "func_a" in payload["functions"]
    assert payload["signatures"]["func_a"] == "(x: int)"
    assert payload["metadata"]["func_a"]["foo"] == "bar"


def test_get_call_records_empty() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_get_call_records", {}))
    payload = _parse_tool_result(result)

    assert payload["calls"] == []
    assert payload["total_count"] == 0
    assert payload["truncated"] is False


def test_get_call_records_all() -> None:
    manager = BreakpointManager()
    manager.record_call({"call_id": "1", "method_name": "process", "status": "success"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_get_call_records", {}))
    payload = _parse_tool_result(result)

    assert len(payload["calls"]) == 1
    assert payload["total_count"] == 1


def test_get_call_records_filtered() -> None:
    manager = BreakpointManager()
    manager.record_call({"call_id": "1", "method_name": "process", "status": "success"})
    manager.record_call({"call_id": "2", "method_name": "other", "status": "success"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_get_call_records", {"function_name": "process"}))
    payload = _parse_tool_result(result)

    assert len(payload["calls"]) == 1
    assert payload["calls"][0]["call_id"] == "1"


def test_get_call_records_with_limit() -> None:
    manager = BreakpointManager()
    for idx in range(3):
        manager.record_call({"call_id": str(idx), "method_name": "process", "status": "success"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_get_call_records", {"limit": 2}))
    payload = _parse_tool_result(result)

    assert len(payload["calls"]) == 2
    assert payload["total_count"] == 3
    assert payload["truncated"] is True


def test_get_call_records_default_limit_100() -> None:
    manager = BreakpointManager()
    for idx in range(120):
        manager.record_call({"call_id": str(idx), "method_name": "process", "status": "success"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_get_call_records", {}))
    payload = _parse_tool_result(result)

    assert len(payload["calls"]) == 100


def test_get_call_records_total_count() -> None:
    manager = BreakpointManager()
    for idx in range(2):
        manager.record_call({"call_id": str(idx), "method_name": "process", "status": "success"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_get_call_records", {"limit": 1}))
    payload = _parse_tool_result(result)

    assert payload["total_count"] == 2


def test_get_call_records_truncated_flag() -> None:
    manager = BreakpointManager()
    for idx in range(2):
        manager.record_call({"call_id": str(idx), "method_name": "process", "status": "success"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.call_tool("breakpoint_get_call_records", {"limit": 5}))
    payload = _parse_tool_result(result)

    assert payload["truncated"] is False


def test_get_call_records_limit_zero_is_error() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_get_call_records", {"limit": 0}))
    payload = _parse_tool_result(result)

    assert payload["error"] == "invalid_limit"


class _FakeReplBackend:
    def __init__(self) -> None:
        self._results: dict[str, dict[str, object]] = {}
        self._counter = 0

    def queue_repl_eval(self, pause_id: str, session_id: str, expr: str) -> str:
        self._counter += 1
        return f"eval-{self._counter}"

    def set_result(self, eval_id: str, result: dict[str, object]) -> None:
        self._results[eval_id] = dict(result)

    def wait_for_repl_eval(
        self, eval_id: str, timeout_s: float
    ) -> tuple[str, dict[str, object] | None]:
        result = self._results.get(eval_id)
        if result is None:
            return ("timeout", None)
        return ("ok", result)


def test_repl_eval_simple_expression() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    backend = _FakeReplBackend()
    backend.set_result("eval-1", {"output": "4", "stdout": "", "is_error": False})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"), repl_backend=backend)

    result = _run(
        server.call_tool(
            "breakpoint_repl_eval",
            {"pause_id": pause_id, "expression": "2 + 2"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["output"] == "4"
    assert payload["is_error"] is False


def test_repl_eval_creates_session() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    backend = _FakeReplBackend()
    backend.set_result("eval-1", {"output": "ok", "stdout": "", "is_error": False})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"), repl_backend=backend)

    result = _run(
        server.call_tool(
            "breakpoint_repl_eval",
            {"pause_id": pause_id, "expression": "1"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["session_id"]


def test_repl_eval_reuses_session() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    session_id = manager.start_repl_session(pause_id)
    backend = _FakeReplBackend()
    backend.set_result("eval-1", {"output": "ok", "stdout": "", "is_error": False})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"), repl_backend=backend)

    result = _run(
        server.call_tool(
            "breakpoint_repl_eval",
            {"pause_id": pause_id, "expression": "1", "session_id": session_id},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["session_id"] == session_id


def test_repl_eval_error_expression() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    backend = _FakeReplBackend()
    backend.set_result("eval-1", {"output": "bad", "stdout": "", "is_error": True})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"), repl_backend=backend)

    result = _run(
        server.call_tool(
            "breakpoint_repl_eval",
            {"pause_id": pause_id, "expression": "bad"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["is_error"] is True


def test_repl_eval_empty_expression() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"), repl_backend=_FakeReplBackend())

    result = _run(
        server.call_tool(
            "breakpoint_repl_eval",
            {"pause_id": pause_id, "expression": "  "},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "missing_expression"


def test_repl_eval_no_paused_execution() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"), repl_backend=_FakeReplBackend())
    result = _run(
        server.call_tool(
            "breakpoint_repl_eval",
            {"pause_id": "missing", "expression": "1"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "pause_not_found"


def test_repl_eval_captures_stdout() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    backend = _FakeReplBackend()
    backend.set_result("eval-1", {"output": "ok", "stdout": "hi", "is_error": False})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"), repl_backend=backend)

    result = _run(
        server.call_tool(
            "breakpoint_repl_eval",
            {"pause_id": pause_id, "expression": "print()"},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["stdout"] == "hi"


def test_repl_eval_timeout() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    backend = _FakeReplBackend()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"), repl_backend=backend)

    result = _run(
        server.call_tool(
            "breakpoint_repl_eval",
            {"pause_id": pause_id, "expression": "1", "timeout_s": 0.01},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "eval_timeout"


def test_repl_eval_closed_session() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process", "process_pid": 1})
    session_id = manager.start_repl_session(pause_id)
    manager.close_repl_session(session_id)
    backend = _FakeReplBackend()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"), repl_backend=backend)

    result = _run(
        server.call_tool(
            "breakpoint_repl_eval",
            {"pause_id": pause_id, "expression": "1", "session_id": session_id},
        )
    )
    payload = _parse_tool_result(result)

    assert payload["error"] == "session_closed"


def test_inspect_object_exists() -> None:
    store = CIDStore(":memory:")
    data = serialize([1, 2, 3])
    cid = hashlib.sha512(data).hexdigest()
    store.store(cid, data)
    server = BreakpointMCPServer(BreakpointManager(), store)

    result = _run(server.call_tool("breakpoint_inspect_object", {"cid": cid}))
    payload = _parse_tool_result(result)

    assert payload["cid"] == cid
    assert payload["type"] == "list"


def test_inspect_object_not_found() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))
    result = _run(server.call_tool("breakpoint_inspect_object", {"cid": "missing"}))
    payload = _parse_tool_result(result)

    assert payload["error"] == "cid_not_found"


def test_inspect_object_corrupted_data() -> None:
    store = CIDStore(":memory:")
    data = b"not a pickle"
    cid = hashlib.sha512(data).hexdigest()
    store.store(cid, data)
    server = BreakpointMCPServer(BreakpointManager(), store)

    result = _run(server.call_tool("breakpoint_inspect_object", {"cid": cid}))
    payload = _parse_tool_result(result)

    assert payload["error"] == "deserialization_failed"


def test_resource_status() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("func_a")
    manager.add_paused_execution({"method_name": "process"})
    manager.record_call({"call_id": "1", "method_name": "process", "status": "success"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.read_resource("breakpoint://status"))
    payload = _parse_resource_result(result)

    assert payload["breakpoints"] == 1
    assert payload["paused"] == 1
    assert payload["total_calls"] == 1


def test_resource_breakpoints_matches_tool() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("func_a")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    resource = _run(server.read_resource("breakpoint://breakpoints"))
    tool = _run(server.call_tool("breakpoint_list_breakpoints", {}))

    assert _parse_resource_result(resource) == _parse_tool_result(tool)


def test_resource_paused_matches_tool() -> None:
    manager = BreakpointManager()
    manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    resource = _run(server.read_resource("breakpoint://paused"))
    tool = _run(server.call_tool("breakpoint_list_paused", {}))

    assert _parse_resource_result(resource) == _parse_tool_result(tool)


def test_resource_call_history_returns_recent() -> None:
    manager = BreakpointManager()
    for idx in range(60):
        manager.record_call({"call_id": str(idx), "method_name": "process", "status": "success"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.read_resource("breakpoint://call-history"))
    payload = _parse_resource_result(result)

    assert len(payload["calls"]) == 50


def test_resource_functions() -> None:
    manager = BreakpointManager()
    manager.register_function("func_a", signature="(x)")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.read_resource("breakpoint://functions"))
    payload = _parse_resource_result(result)

    assert "func_a" in payload["functions"]


def test_resource_status_updates_dynamically() -> None:
    manager = BreakpointManager()
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    initial = _parse_resource_result(_run(server.read_resource("breakpoint://status")))
    manager.add_breakpoint("func_a")
    updated = _parse_resource_result(_run(server.read_resource("breakpoint://status")))

    assert updated["breakpoints"] == initial["breakpoints"] + 1


def test_prompt_debug_session_start() -> None:
    manager = BreakpointManager()
    manager.add_breakpoint("func_a")
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.get_prompt("debug-session-start", {}))
    assert result.messages


def test_prompt_inspect_paused_call() -> None:
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"method_name": "process"})
    server = BreakpointMCPServer(manager, CIDStore(":memory:"))

    result = _run(server.get_prompt("inspect-paused-call", {"pause_id": pause_id}))
    assert result.messages


def test_prompt_inspect_paused_call_not_found() -> None:
    server = BreakpointMCPServer(BreakpointManager(), CIDStore(":memory:"))

    with pytest.raises(ValueError):
        _run(server.get_prompt("inspect-paused-call", {"pause_id": "missing"}))
