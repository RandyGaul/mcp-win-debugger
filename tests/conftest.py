"""Shared fixtures for windbg-mcp tests."""

import os
import pathlib
import sys
import pytest

# Add src/ to import path so tests can import directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cdb import CdbProcess, find_cdb

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


def cdb_available() -> bool:
    """Check if cdb.exe is available on this system."""
    try:
        find_cdb()
        return True
    except FileNotFoundError:
        return False


def find_crashme() -> str | None:
    """Find the crashme.exe test fixture. Checks pre-built and cmake build dirs."""
    candidates = [
        FIXTURES_DIR / "crashme.exe",
        FIXTURES_DIR / "build" / "crashme.exe",
        FIXTURES_DIR / "build" / "Debug" / "crashme.exe",
        FIXTURES_DIR / "build" / "Release" / "crashme.exe",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def find_crashme_pdb() -> str | None:
    """Find the directory containing crashme.pdb."""
    exe = find_crashme()
    if not exe:
        return None
    exe_dir = pathlib.Path(exe).parent
    if (exe_dir / "crashme.pdb").is_file():
        return str(exe_dir)
    if (FIXTURES_DIR / "crashme.pdb").is_file():
        return str(FIXTURES_DIR)
    return None


requires_cdb = pytest.mark.skipif(
    not cdb_available(),
    reason="cdb.exe not found — install Windows SDK Debugging Tools",
)

requires_crashme = pytest.mark.skipif(
    find_crashme() is None,
    reason="crashme.exe not found — build tests/fixtures/ with cmake first",
)


@pytest.fixture(scope="module")
async def cdb_crashme():
    """Launch crashme.exe under cdb ONCE per test module. Reused across tests."""
    exe = find_crashme()
    pdb_dir = find_crashme_pdb()
    assert exe, "crashme.exe not found"

    cdb = CdbProcess()
    if pdb_dir:
        cdb.initial_symbol_path = pdb_dir
    await cdb.launch_executable(exe)
    if pdb_dir:
        await cdb.execute(".reload /f crashme.exe")
    yield cdb
    await cdb.quit()


@pytest.fixture(scope="module")
async def cdb_notepad():
    """Launch notepad.exe under cdb ONCE per test module. Reused across tests."""
    cdb = CdbProcess()
    await cdb.launch_executable("notepad.exe")
    yield cdb
    await cdb.quit()


@pytest.fixture
async def cdb_notepad_fresh():
    """Launch a fresh notepad.exe session (slow — use only when test needs clean state)."""
    cdb = CdbProcess()
    await cdb.launch_executable("notepad.exe")
    yield cdb
    await cdb.quit()


@pytest.fixture
async def cdb_session():
    """Provide an unattached CdbProcess instance."""
    return CdbProcess()
