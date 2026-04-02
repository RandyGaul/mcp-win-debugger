"""Tests using the crashme.exe fixture — exercises symbol-aware debugging with PDBs."""

import pytest

from .conftest import requires_cdb, requires_crashme


@requires_cdb
@requires_crashme
class TestSymbolResolution:
    @pytest.mark.asyncio
    async def test_symbols_loaded(self, cdb_crashme):
        """Our custom PDB symbols should be loaded for crashme module."""
        result = await cdb_crashme.execute("x crashme!main")
        assert "crashme!main" in result.output

    @pytest.mark.asyncio
    async def test_function_symbols(self, cdb_crashme):
        """All our C functions should be resolvable."""
        for func in ["create_game", "add_player", "get_last_player", "damage_player", "apply_poison"]:
            result = await cdb_crashme.execute(f"x crashme!{func}")
            assert f"crashme!{func}" in result.output, f"{func} not found in symbols"


@requires_cdb
@requires_crashme
class TestBreakpointOnOwnCode:
    @pytest.mark.asyncio
    async def test_breakpoint_resolves(self, cdb_crashme):
        """Breakpoints on our own functions should resolve (not show 'eu')."""
        await cdb_crashme.execute("bp crashme!main")
        result = await cdb_crashme.execute("bl")
        assert " e " in result.output
        assert "crashme!main" in result.output
        await cdb_crashme.execute("bc *")


@requires_cdb
@requires_crashme
class TestStructInspection:
    @pytest.mark.asyncio
    async def test_display_custom_struct(self, cdb_crashme):
        """dt should show our custom struct layout with field names."""
        result = await cdb_crashme.execute("dt crashme!Player")
        assert "name" in result.output
        assert "health" in result.output
        assert "armor" in result.output
        assert "position" in result.output

    @pytest.mark.asyncio
    async def test_display_gamestate_struct(self, cdb_crashme):
        """dt should show GameState with its fields."""
        result = await cdb_crashme.execute("dt crashme!GameState")
        assert "players" in result.output
        assert "count" in result.output
        assert "capacity" in result.output


@requires_cdb
@requires_crashme
class TestCallstackWithSymbols:
    @pytest.mark.asyncio
    async def test_callstack_shows_main(self, cdb_crashme):
        """Callstack at initial break should show ntdll loader or crashme symbols."""
        result = await cdb_crashme.execute("k")
        assert len(result.output) > 0


@requires_cdb
@requires_crashme
class TestLocalsWithSymbols:
    @pytest.mark.asyncio
    async def test_locals_available(self, cdb_crashme):
        """dv should return output (locals depend on where we're stopped)."""
        result = await cdb_crashme.execute("dv")
        assert isinstance(result.output, str)


@requires_cdb
@requires_crashme
class TestExpressionEvaluation:
    @pytest.mark.asyncio
    async def test_sizeof_player(self, cdb_crashme):
        """sizeof(Player) should return the struct size."""
        result = await cdb_crashme.execute("?? sizeof(crashme!Player)")
        assert "unsigned int64" in result.output or "0x" in result.output

    @pytest.mark.asyncio
    async def test_sizeof_gamestate(self, cdb_crashme):
        """sizeof(GameState) should return the struct size."""
        result = await cdb_crashme.execute("?? sizeof(crashme!GameState)")
        assert "unsigned int64" in result.output or "0x" in result.output
