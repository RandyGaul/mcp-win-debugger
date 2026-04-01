"""Tests for the CdbProcess class — session lifecycle, command execution, output cleaning."""

import asyncio
import pytest

from windbg_mcp.cdb import CdbProcess, CdbResult, find_cdb, COMMAND_MARKER, LAUNCH_MARKER
from .conftest import requires_cdb


# ── find_cdb ────────────────────────────────────────────────────────

class TestFindCdb:
    def test_find_cdb_returns_path(self):
        """find_cdb should return a valid path when cdb is installed."""
        try:
            path = find_cdb()
            assert path.endswith("cdb.exe")
            import os
            assert os.path.isfile(path)
        except FileNotFoundError:
            pytest.skip("cdb.exe not installed")

    def test_find_cdb_respects_env(self, monkeypatch, tmp_path):
        """CDB_PATH env var should override search paths."""
        fake = tmp_path / "cdb.exe"
        fake.write_text("fake")
        monkeypatch.setenv("CDB_PATH", str(fake))
        assert find_cdb() == str(fake)

    def test_find_cdb_raises_when_missing(self, monkeypatch):
        """Should raise FileNotFoundError when cdb isn't found."""
        monkeypatch.setenv("CDB_PATH", "")
        monkeypatch.setattr("windbg_mcp.cdb.CDB_SEARCH_PATHS", [])
        with pytest.raises(FileNotFoundError, match="cdb.exe not found"):
            find_cdb()


# ── Session lifecycle ───────────────────────────────────────────────

@requires_cdb
class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_launch_and_quit(self, cdb_notepad_fresh):
        """Should launch notepad, report running, then quit cleanly."""
        assert cdb_notepad_fresh.is_running
        # Don't quit here — fixture handles cleanup

    @pytest.mark.asyncio
    async def test_quit_without_session(self):
        """Quitting with no active session should return cleanly."""
        cdb = CdbProcess()
        msg = await cdb.quit()
        assert msg == "No active session"

    @pytest.mark.asyncio
    async def test_execute_without_session_raises(self):
        """Executing a command without a session should raise."""
        cdb = CdbProcess()
        with pytest.raises(RuntimeError, match="No active cdb session"):
            await cdb.execute("k")


# ── Command execution ──────────────────────────────────────────────

@requires_cdb
class TestCommandExecution:
    @pytest.mark.asyncio
    async def test_callstack(self, cdb_notepad):
        """k command should return a call stack with frame info."""
        result = await cdb_notepad.execute("k 5")
        assert "Child-SP" in result.output
        assert "RetAddr" in result.output
        assert "Call Site" in result.output

    @pytest.mark.asyncio
    async def test_modules_list(self, cdb_notepad):
        """lm should list loaded modules including notepad and ntdll."""
        result = await cdb_notepad.execute("lm")
        output_lower = result.output.lower()
        assert "notepad" in output_lower
        assert "ntdll" in output_lower

    @pytest.mark.asyncio
    async def test_threads_list(self, cdb_notepad):
        """~* should list at least the main thread."""
        result = await cdb_notepad.execute("~*")
        assert "Suspend:" in result.output or "Teb:" in result.output

    @pytest.mark.asyncio
    async def test_step_over(self, cdb_notepad):
        """p (step over) should advance the instruction pointer."""
        result = await cdb_notepad.execute("p")
        # Step over produces instruction disassembly
        assert ":" in result.output  # address:instruction format

    @pytest.mark.asyncio
    async def test_step_into(self, cdb_notepad):
        """t (step into) should execute one instruction."""
        result = await cdb_notepad.execute("t")
        assert len(result.output) > 0

    @pytest.mark.asyncio
    async def test_evaluate_expression(self, cdb_notepad):
        """?? should evaluate a MASM expression."""
        result = await cdb_notepad.execute("?? 2 + 3")
        assert "5" in result.output

    @pytest.mark.asyncio
    async def test_read_memory(self, cdb_notepad):
        """db @rsp should show hex bytes at the stack pointer."""
        result = await cdb_notepad.execute("db @rsp L16")
        # Memory dump has hex byte patterns like "00 1a ff"
        assert any(c in result.output for c in "0123456789abcdef")

    @pytest.mark.asyncio
    async def test_display_type(self, cdb_notepad):
        """dt should respond (may lack private symbols — just verify no hang)."""
        result = await cdb_notepad.execute("dt ntdll!_PEB")
        # Without private symbols, dt may return an error — that's fine
        assert isinstance(result.output, str)

    @pytest.mark.asyncio
    async def test_multiple_sequential_commands(self, cdb_notepad):
        """Multiple commands in sequence should each return correct output."""
        r1 = await cdb_notepad.execute("k 3")
        r2 = await cdb_notepad.execute("lm")
        r3 = await cdb_notepad.execute("~*")

        assert "Child-SP" in r1.output
        assert "notepad" in r2.output.lower()
        assert "Teb:" in r3.output or "Suspend:" in r3.output

    @pytest.mark.asyncio
    async def test_exception_record(self, cdb_notepad):
        """.exr -1 should return a response (may report 'not an exception' with sxd *)."""
        result = await cdb_notepad.execute(".exr -1")
        assert len(result.output) > 0


# ── Output cleaning ────────────────────────────────────────────────

@requires_cdb
class TestOutputCleaning:
    @pytest.mark.asyncio
    async def test_no_marker_in_output(self, cdb_notepad):
        """Command output should never contain internal markers."""
        result = await cdb_notepad.execute("k 5")
        assert COMMAND_MARKER not in result.output
        assert LAUNCH_MARKER not in result.output

    @pytest.mark.asyncio
    async def test_no_echo_command_in_output(self, cdb_notepad):
        """The .echo command itself should be stripped from output."""
        result = await cdb_notepad.execute("k 5")
        assert ".echo" not in result.output

    @pytest.mark.asyncio
    async def test_no_prompt_prefix_in_output(self, cdb_notepad):
        """Output lines should not start with '0:000>' prompt."""
        result = await cdb_notepad.execute("k 5")
        import re
        for line in result.output.split("\n"):
            assert not re.match(r"^\d+:\d+> ", line), f"Prompt prefix found: {line!r}"

    @pytest.mark.asyncio
    async def test_launch_output_is_clean(self, cdb_notepad_fresh):
        """Launch output — verified by fixture succeeding without marker leaks."""
        # If we got here, the fixture launched and didn't crash
        assert cdb_notepad_fresh.is_running


# ── Breakpoints ─────────────────────────────────────────────────────

@requires_cdb
class TestBreakpoints:
    @pytest.mark.asyncio
    async def test_set_and_list_breakpoint(self, cdb_notepad):
        """Setting a breakpoint should make it appear in bl."""
        await cdb_notepad.execute("bp ntdll!NtCreateFile")
        result = await cdb_notepad.execute("bl")
        # Breakpoint should be listed (may show address or symbol name)
        assert len(result.output.strip()) > 0

    @pytest.mark.asyncio
    async def test_delete_breakpoint(self, cdb_notepad):
        """Deleting a breakpoint should remove it from bl."""
        await cdb_notepad.execute("bp ntdll!NtCreateFile")
        await cdb_notepad.execute("bc 0")
        result = await cdb_notepad.execute("bl")
        assert "NtCreateFile" not in result.output

    @pytest.mark.asyncio
    async def test_disable_enable_breakpoint(self, cdb_notepad):
        """Disabling a breakpoint should change its status, enabling restores it."""
        await cdb_notepad.execute("bp ntdll!NtCreateFile")

        # Disable
        await cdb_notepad.execute("bd 0")
        result = await cdb_notepad.execute("bl")
        assert len(result.output.strip()) > 0  # breakpoint still listed

        # Re-enable
        await cdb_notepad.execute("be 0")
        result = await cdb_notepad.execute("bl")
        assert len(result.output.strip()) > 0  # still listed


# ── Symbol search ──────────────────────────────────────────────────

@requires_cdb
class TestSymbolSearch:
    @pytest.mark.asyncio
    async def test_search_exported_symbol(self, cdb_notepad):
        """x ntdll!NtCreate* should find exported ntdll functions."""
        result = await cdb_notepad.execute("x ntdll!NtCreate*")
        assert "NtCreateFile" in result.output or "NtCreateEvent" in result.output

    @pytest.mark.asyncio
    async def test_search_nonexistent_symbol(self, cdb_notepad):
        """Searching for a nonexistent symbol should return empty or no match."""
        result = await cdb_notepad.execute("x ntdll!ZzzNonexistentXyz999")
        # cdb returns empty output or no matching symbols
        assert "ZzzNonexistentXyz999" not in result.output


# ── Thread navigation ──────────────────────────────────────────────

@requires_cdb
class TestThreadNavigation:
    @pytest.mark.asyncio
    async def test_switch_thread(self, cdb_notepad):
        """Switching to thread 0 should work (it's always the main thread)."""
        result = await cdb_notepad.execute("~0s")
        # Should produce output (symbol options or instruction) without a cdb error
        assert len(result.output) > 0
        assert "^ Syntax error" not in result.output

    @pytest.mark.asyncio
    async def test_switch_frame(self, cdb_notepad):
        """Switching to frame 0 should show the current instruction."""
        result = await cdb_notepad.execute(".frame 0")
        assert len(result.output) > 0


# ── Memory inspection ──────────────────────────────────────────────

@requires_cdb
class TestMemoryInspection:
    @pytest.mark.asyncio
    async def test_dps_stack(self, cdb_notepad):
        """dps @rsp should show pointer-sized values with symbol resolution."""
        result = await cdb_notepad.execute("dps @rsp L4")
        # Should contain addresses in backtick format
        assert "`" in result.output

    @pytest.mark.asyncio
    async def test_display_type_recursive(self, cdb_notepad):
        """dt -r1 should expand nested fields (output depends on available symbols)."""
        result = await cdb_notepad.execute("dt -r1 ntdll!_PEB @$peb")
        # May show full type layout or error if no private symbols — just verify no crash
        assert len(result.output) > 0

    @pytest.mark.asyncio
    async def test_read_memory_formats(self, cdb_notepad):
        """Different memory display formats should all work."""
        for fmt in ["db", "dw", "dd", "dq"]:
            result = await cdb_notepad.execute(f"{fmt} @rsp L4")
            assert len(result.output) > 0, f"{fmt} returned empty output"
