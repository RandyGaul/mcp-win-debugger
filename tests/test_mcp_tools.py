"""Tests for MCP server tools — validates each tool returns meaningful output."""

import asyncio
import pytest

import server
from cdb import CdbProcess
from .conftest import requires_cdb


@pytest.fixture(autouse=True)
async def reset_server_state():
    """Reset the global cdb session between tests."""
    server._cdb = None
    yield
    if server._cdb and server._cdb.is_running:
        await server._cdb.quit()
    server._cdb = None


@pytest.fixture
async def active_session():
    """Launch notepad via the MCP launch tool (paused at initial break)."""
    output = await server.launch("notepad.exe")
    assert "notepad" in output.lower() or "ModLoad" in output or "Break" in output
    yield


# ── Session tools ──────────────────────────────────────────────────

@requires_cdb
class TestSessionTools:
    @pytest.mark.asyncio
    async def test_launch_creates_session(self):
        output = await server.launch("notepad.exe")
        assert "ModLoad" in output or "Break" in output

    @pytest.mark.asyncio
    async def test_detach_ends_session(self, active_session):
        result = await server.detach()
        assert result == "Session ended"

    @pytest.mark.asyncio
    async def test_tools_fail_without_session(self):
        """All inspection tools should raise when no session is active."""
        with pytest.raises(RuntimeError, match="No active debug session"):
            await server.callstack()


# ── Execution control tools ────────────────────────────────────────

@requires_cdb
class TestExecutionTools:
    @pytest.mark.asyncio
    async def test_step_into(self, active_session):
        result = await server.step_into()
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_step_over(self, active_session):
        result = await server.step_over()
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_step_out(self, active_session):
        """step_out (gu) from the initial break may hit end of stack, but shouldn't crash."""
        result = await server.step_out()
        assert isinstance(result, str)


# ── Breakpoint tools ──────────────────────────────────────────────

@requires_cdb
class TestBreakpointTools:
    @pytest.mark.asyncio
    async def test_set_breakpoint(self, active_session):
        result = await server.set_breakpoint("ntdll!NtCreateFile")
        assert "NtCreateFile" in result

    @pytest.mark.asyncio
    async def test_list_breakpoints_empty(self, active_session):
        result = await server.list_breakpoints()
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_breakpoint_lifecycle(self, active_session):
        """Set -> list -> disable -> enable -> delete cycle."""
        await server.set_breakpoint("ntdll!NtCreateFile")
        listed = await server.list_breakpoints()
        assert "NtCreateFile" in listed
        await server.disable_breakpoint(0)
        await server.enable_breakpoint(0)
        await server.delete_breakpoint(0)
        listed = await server.list_breakpoints()
        assert "NtCreateFile" not in listed

    @pytest.mark.asyncio
    async def test_set_data_breakpoint(self, active_session):
        """Setting a data breakpoint on rsp should work."""
        result = await server.set_data_breakpoint("@rsp", size=4, access="w")
        assert isinstance(result, str)
        await server.delete_breakpoint(0)


# ── Inspection tools ──────────────────────────────────────────────

@requires_cdb
class TestInspectionTools:
    @pytest.mark.asyncio
    async def test_callstack(self, active_session):
        result = await server.callstack()
        assert "Child-SP" in result
        assert "Call Site" in result

    @pytest.mark.asyncio
    async def test_callstack_all_threads(self, active_session):
        result = await server.callstack(depth=5, all_threads=True)
        assert "Teb:" in result or "Id:" in result or "#" in result

    @pytest.mark.asyncio
    async def test_locals(self, active_session):
        result = await server.locals()
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_evaluate(self, active_session):
        result = await server.evaluate("1 + 1")
        assert "2" in result

    @pytest.mark.asyncio
    async def test_display_type(self, active_session):
        result = await server.display_type("ntdll!_PEB")
        assert "BeingDebugged" in result or "ImageBaseAddress" in result

    @pytest.mark.asyncio
    async def test_display_type_recursive(self, active_session):
        result = await server.display_type_recursive("ntdll!_PEB", "@$peb", depth=1)
        assert len(result) > 100

    @pytest.mark.asyncio
    async def test_read_memory_bytes(self, active_session):
        result = await server.read_memory("@rsp", length=16, format="bytes")
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_read_memory_qwords(self, active_session):
        result = await server.read_memory("@rsp", length=4, format="qwords")
        assert "`" in result

    @pytest.mark.asyncio
    async def test_dereference_pointer(self, active_session):
        result = await server.dereference_pointer("@rsp")
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_inspect_object(self, active_session):
        result = await server.inspect_object("@rsp")
        assert "Memory (with symbols)" in result

    @pytest.mark.asyncio
    async def test_inspect_object_with_type(self, active_session):
        result = await server.inspect_object("@$peb", type_name="ntdll!_PEB")
        assert "Memory (with symbols)" in result
        assert "Type Layout" in result


# ── Thread tools ──────────────────────────────────────────────────

@requires_cdb
class TestThreadTools:
    @pytest.mark.asyncio
    async def test_threads(self, active_session):
        result = await server.threads()
        assert "Id:" in result or "Teb:" in result

    @pytest.mark.asyncio
    async def test_switch_thread(self, active_session):
        result = await server.switch_thread(0)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_switch_frame(self, active_session):
        result = await server.switch_frame(0)
        assert isinstance(result, str)


# ── Module & symbol tools ─────────────────────────────────────────

@requires_cdb
class TestModuleTools:
    @pytest.mark.asyncio
    async def test_modules(self, active_session):
        result = await server.modules()
        assert "notepad" in result.lower()
        assert "ntdll" in result.lower()

    @pytest.mark.asyncio
    async def test_search_symbol(self, active_session):
        result = await server.search_symbol("ntdll!NtCreate*")
        assert "NtCreate" in result

    @pytest.mark.asyncio
    async def test_reload_symbols(self, active_session):
        result = await server.reload_symbols()
        assert isinstance(result, str)


# ── Analysis tools ────────────────────────────────────────────────

@requires_cdb
class TestAnalysisTools:
    @pytest.mark.asyncio
    async def test_exception_record(self, active_session):
        result = await server.exception_record()
        assert "Exception" in result or "80000003" in result


# ── Raw command tool ──────────────────────────────────────────────

@requires_cdb
class TestRawCommand:
    @pytest.mark.asyncio
    async def test_cdb_command(self, active_session):
        result = await server.cdb_command("? 0x10 + 0x20")
        assert "30" in result.lower() or "48" in result

    @pytest.mark.asyncio
    async def test_cdb_command_formats(self, active_session):
        result = await server.cdb_command(".formats 0x42")
        assert "Decimal" in result or "Hex" in result or "66" in result
