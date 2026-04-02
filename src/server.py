"""
WinDbg MCP Server — exposes cdb.exe debugging as MCP tools.

No external dependencies. Run directly:
    python src/server.py
"""

import asyncio
import logging
import pathlib
import sys

try:
    from .mcp_server import McpServer
    from .cdb import CdbProcess
except ImportError:
    from mcp_server import McpServer
    from cdb import CdbProcess

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

mcp = McpServer("windbg")

# ── Load prompt templates ───────────────────────────────────────────

_PROMPTS_DIR = pathlib.Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.prompt.md"
    return path.read_text(encoding="utf-8")


@mcp.prompt()
def live_debug() -> str:
    """Guided workflow for investigating a bug in a live running process.
    Covers: launch, symbols, breakpoints, inspection, stepping, and state modification."""
    return _load_prompt("live-debug")


@mcp.prompt()
def crash_triage() -> str:
    """Systematic workflow for triaging a crash dump (.dmp file).
    Covers: open dump, auto-analysis, callstacks, memory inspection, and reporting."""
    return _load_prompt("crash-triage")


@mcp.prompt()
def memory_corruption() -> str:
    """Investigation workflow for memory corruption bugs using data breakpoints.
    Covers: identifying corrupted data, setting hardware watchpoints, catching the corruptor."""
    return _load_prompt("memory-corruption")


# Single shared cdb session (one debug target at a time)
_cdb: CdbProcess | None = None


def _get_cdb() -> CdbProcess:
    global _cdb
    if _cdb is None:
        _cdb = CdbProcess()
    return _cdb


def _require_session() -> CdbProcess:
    cdb = _get_cdb()
    if not cdb.is_running:
        raise RuntimeError("No active debug session. Use open_dump, launch, or attach first.")
    return cdb


# ── Session management ──────────────────────────────────────────────

@mcp.tool()
async def open_dump(path: str, symbol_path: str = "") -> str:
    """Open a minidump (.dmp) file for post-mortem analysis.

    Args:
        path: Path to the .dmp file
        symbol_path: Optional symbol path (srv* for Microsoft symbol server)
    """
    cdb = _get_cdb()
    result = await cdb.open_dump(path, symbol_path or None)
    return result.output


@mcp.tool()
async def launch(executable: str, args: str = "", symbol_path: str = "") -> str:
    """Launch an executable under the debugger, paused at initial break.

    Fast startup: no symbols loaded, no unqualified symbol lookups, exception
    noise suppressed (only access violations break by default).

    Recommended workflow:
      1. launch(exe, symbol_path='D:/build/dir')
      2. load_symbols_for('mymodule')
      3. set_breakpoint('mymodule!MyFunc')
      4. go()

    Args:
        executable: Path to the .exe to debug
        args: Optional command-line arguments (space-separated)
        symbol_path: Directory containing PDB files for YOUR code. Leave empty for no symbols.
    """
    cdb = _get_cdb()
    if symbol_path:
        cdb.initial_symbol_path = symbol_path
    exe_args = args.split() if args else None
    result = await cdb.launch_executable(executable, exe_args)
    return result.output


@mcp.tool()
async def attach(pid: int) -> str:
    """Attach the debugger to a running process.

    Args:
        pid: Process ID to attach to
    """
    cdb = _get_cdb()
    result = await cdb.attach(pid)
    return result.output


@mcp.tool()
async def detach() -> str:
    """Detach from the current debug target and end the session."""
    cdb = _get_cdb()
    return await cdb.quit()


# ── Execution control ───────────────────────────────────────────────

@mcp.tool()
async def go(breakpoint_id: int = -1) -> str:
    """Continue execution (F5). Runs until a breakpoint, exception, or program exit.

    Args:
        breakpoint_id: Optional breakpoint ID to continue to a specific breakpoint
    """
    cdb = _require_session()
    cmd = f"g" if breakpoint_id < 0 else f"g @$bp{breakpoint_id}"
    result = await cdb.execute(cmd, timeout=60.0)
    return result.output


@mcp.tool()
async def step_into() -> str:
    """Step into the next source line (F11). Follows calls into functions.

    Steps by source line when symbols with line info are loaded (skips
    prologue instructions automatically). Falls back to instruction-level
    stepping when no source info is available."""
    cdb = _require_session()
    result = await cdb.execute("t")
    return result.output


@mcp.tool()
async def step_over() -> str:
    """Step over the next source line (F10). Executes calls without entering them.

    Steps by source line when symbols with line info are loaded (skips
    prologue instructions automatically). Falls back to instruction-level
    stepping when no source info is available."""
    cdb = _require_session()
    result = await cdb.execute("p")
    return result.output


@mcp.tool()
async def step_out() -> str:
    """Step out of the current function (Shift+F11). Runs until the current function returns."""
    cdb = _require_session()
    result = await cdb.execute("gu")
    return result.output


@mcp.tool()
async def break_execution() -> str:
    """Break into the debugger (Ctrl+Break). Stops the target if it's running."""
    cdb = _require_session()
    await cdb.send_break()
    await asyncio.sleep(0.5)
    result = await cdb.execute("")
    return result.output


# ── Breakpoints ─────────────────────────────────────────────────────

@mcp.tool()
async def set_breakpoint(expression: str, condition: str = "") -> str:
    """Set a breakpoint at a function, address, or source location.

    When a function breakpoint hits, you land at the very start of the function.
    Use step_over once to advance past the prologue to the first source line where
    locals are initialized. To read arguments before the prologue, use evaluate
    with register names (@rcx, @rdx, @r8, @r9 for the first four args on x64).

    Args:
        expression: Breakpoint location — function name (e.g. 'main'), address (0x...), or source (file.cpp:42)
        condition: Optional condition expression (breakpoint only triggers when true)
    """
    cdb = _require_session()
    cmd = f'bp {expression}'
    if condition:
        cmd = f'bp /w "{condition}" {expression}'
    result = await cdb.execute(cmd)
    # Also return the breakpoint list so we can see the ID
    bl = await cdb.execute("bl")
    return f"{result.output}\n{bl.output}"


@mcp.tool()
async def list_breakpoints() -> str:
    """List all active breakpoints with their IDs, addresses, and status."""
    cdb = _require_session()
    result = await cdb.execute("bl")
    return result.output or "No breakpoints set."


@mcp.tool()
async def delete_breakpoint(breakpoint_id: int) -> str:
    """Delete a breakpoint by its ID.

    Args:
        breakpoint_id: The breakpoint number from list_breakpoints
    """
    cdb = _require_session()
    result = await cdb.execute(f"bc {breakpoint_id}")
    return result.output or f"Breakpoint {breakpoint_id} deleted."


@mcp.tool()
async def enable_breakpoint(breakpoint_id: int) -> str:
    """Enable a disabled breakpoint.

    Args:
        breakpoint_id: The breakpoint number to enable
    """
    cdb = _require_session()
    result = await cdb.execute(f"be {breakpoint_id}")
    return result.output or f"Breakpoint {breakpoint_id} enabled."


@mcp.tool()
async def disable_breakpoint(breakpoint_id: int) -> str:
    """Disable a breakpoint without deleting it.

    Args:
        breakpoint_id: The breakpoint number to disable
    """
    cdb = _require_session()
    result = await cdb.execute(f"bd {breakpoint_id}")
    return result.output or f"Breakpoint {breakpoint_id} disabled."


@mcp.tool()
async def set_data_breakpoint(address: str, size: int = 4, access: str = "w") -> str:
    """Set a hardware data breakpoint (watchpoint) that triggers on memory access.

    Args:
        address: Memory address or expression to watch
        size: Number of bytes to watch (1, 2, 4, or 8)
        access: Access type — 'w' (write only), 'r' (read only), 'rw' (read/write)
    """
    cdb = _require_session()
    access_map = {"w": "w", "r": "r", "rw": "rw"}
    acc = access_map.get(access, "w")
    result = await cdb.execute(f"ba {acc} {size} {address}")
    bl = await cdb.execute("bl")
    return f"{result.output}\n{bl.output}"


# ── Inspection ──────────────────────────────────────────────────────

@mcp.tool()
async def callstack(depth: int = 20, all_threads: bool = False) -> str:
    """Get the call stack of the current (or all) thread(s).

    Args:
        depth: Maximum number of frames to show (default 20)
        all_threads: If True, show stacks for all threads
    """
    cdb = _require_session()
    if all_threads:
        result = await cdb.execute(f"~*k {depth}")
    else:
        result = await cdb.execute(f"k {depth}")
    return result.output


@mcp.tool()
async def locals() -> str:
    """Display local variables in the current scope. Requires private symbols."""
    cdb = _require_session()
    result = await cdb.execute("dv /t /v")
    return result.output


@mcp.tool()
async def evaluate(expression: str) -> str:
    """Evaluate a C++ expression and print the result.

    Tip: If you need to evaluate multiple expressions while stopped at a breakpoint,
    disable the breakpoint first to avoid re-fire collisions that produce stale output.
    Alternatively, use cdb_command with semicolons to batch evaluations in one call.

    Args:
        expression: C++ expression to evaluate (e.g. 'myVar', 'ptr->field', 'sizeof(MyStruct)')
    """
    cdb = _require_session()
    result = await cdb.execute(f"?? {expression}")
    return result.output


@mcp.tool()
async def display_type(type_or_address: str, address: str = "") -> str:
    """Display a type layout or the contents of a struct/class at an address.

    Args:
        type_or_address: Type name (e.g. 'MyStruct') or module!type
        address: Optional memory address to display an instance at
    """
    cdb = _require_session()
    cmd = f"dt {type_or_address}"
    if address:
        cmd += f" {address}"
    result = await cdb.execute(cmd)
    return result.output


@mcp.tool()
async def read_memory(address: str, length: int = 64, format: str = "bytes") -> str:
    """Read raw memory at an address.

    Args:
        address: Memory address (hex, e.g. '0x7ff...') or symbol
        length: Number of elements to display
        format: 'bytes' (db), 'words' (dw), 'dwords' (dd), 'qwords' (dq), 'ascii' (da), 'unicode' (du)
    """
    cdb = _require_session()
    fmt_map = {
        "bytes": "db", "words": "dw", "dwords": "dd",
        "qwords": "dq", "ascii": "da", "unicode": "du",
    }
    cmd_prefix = fmt_map.get(format, "db")
    result = await cdb.execute(f"{cmd_prefix} {address} L{length}")
    return result.output


# ── Threads ─────────────────────────────────────────────────────────

@mcp.tool()
async def threads() -> str:
    """List all threads in the target process."""
    cdb = _require_session()
    result = await cdb.execute("~*")
    return result.output


@mcp.tool()
async def switch_thread(thread_id: int) -> str:
    """Switch to a different thread.

    Args:
        thread_id: Thread number to switch to (from threads list)
    """
    cdb = _require_session()
    result = await cdb.execute(f"~{thread_id}s")
    return result.output


@mcp.tool()
async def switch_frame(frame_number: int) -> str:
    """Switch to a different stack frame in the current thread.

    Args:
        frame_number: Frame number (0 = top of stack)
    """
    cdb = _require_session()
    result = await cdb.execute(f".frame {frame_number}")
    return result.output


# ── Modules & symbols ──────────────────────────────────────────────

@mcp.tool()
async def modules() -> str:
    """List all loaded modules (DLLs/EXEs) with their address ranges."""
    cdb = _require_session()
    result = await cdb.execute("lm")
    return result.output


@mcp.tool()
async def set_symbol_path(path: str, append: bool = False, cache_dir: str = "") -> str:
    """Set the symbol search path. Controls which PDBs get loaded.

    For large projects, set this to ONLY the directory containing YOUR PDB
    to avoid slow symbol loading from all dependencies.

    Args:
        path: Symbol path — directory containing PDB files, or srv* for symbol server.
              Multiple paths separated by semicolons.
        append: If True, append to existing path instead of replacing.
        cache_dir: Local directory to cache downloaded symbols (e.g. 'D:/symcache').
                   If set, prepends 'cache*<dir>;' to the path so symbols are cached locally.
    """
    cdb = _require_session()
    if cache_dir:
        path = f"cache*{cache_dir};{path}"
    cmd = f".sympath+ {path}" if append else f".sympath {path}"
    result = await cdb.execute(cmd)
    reload_result = await cdb.execute(".reload")
    return f"{result.output}\n{reload_result.output}"


@mcp.tool()
async def reload_symbols(module: str = "") -> str:
    """Force reload symbols, optionally for a specific module.

    Args:
        module: Optional module name to reload symbols for (e.g. 'myapp' for myapp.exe)
    """
    cdb = _require_session()
    cmd = f".reload /f {module}" if module else ".reload /f"
    result = await cdb.execute(cmd, timeout=60.0)
    return result.output


@mcp.tool()
async def load_symbols_for(module: str, pdb_path: str = "") -> str:
    """Load symbols for a specific module only. Fast alternative to loading all symbols.

    Use this when you only care about debugging one module (your own code) and want
    to skip slow symbol loading for all dependencies.

    Args:
        module: Module name (e.g. 'myapp' for myapp.exe, 'engine' for engine.dll)
        pdb_path: Optional path to the PDB file. If omitted, uses the current symbol path.
    """
    cdb = _require_session()
    parts = []

    # Enable source line info loading and source-level stepping
    await cdb.execute(".symopt+0x10")
    await cdb.execute("l+t")

    if pdb_path:
        add_result = await cdb.execute(f".sympath+ {pdb_path}")
        parts.append(add_result.output)

    load_result = await cdb.execute(f".reload /f {module}", timeout=60.0)
    parts.append(load_result.output)

    check_result = await cdb.execute(f"lm vm {module}")
    parts.append(check_result.output)

    return "\n".join(parts)


@mcp.tool()
async def noisy_symbol_loading(enable: bool = True) -> str:
    """Toggle verbose symbol loading output. Useful for diagnosing why symbols aren't loading.

    Args:
        enable: True to enable verbose output, False to disable
    """
    cdb = _require_session()
    cmd = "!sym noisy" if enable else "!sym quiet"
    result = await cdb.execute(cmd)
    return result.output


# ── Crash analysis ──────────────────────────────────────────────────

@mcp.tool()
async def analyze_crash(verbose: bool = True) -> str:
    """Run automatic crash analysis (!analyze). Best used on crash dumps or after an exception.

    Args:
        verbose: Show verbose analysis (default True)
    """
    cdb = _require_session()
    cmd = "!analyze -v" if verbose else "!analyze"
    result = await cdb.execute(cmd, timeout=120.0)
    return result.output


@mcp.tool()
async def exception_record() -> str:
    """Display the current exception record (what caused the crash/break)."""
    cdb = _require_session()
    result = await cdb.execute(".exr -1")
    return result.output


@mcp.tool()
async def display_type_recursive(type_name: str, address: str, depth: int = 2) -> str:
    """Recursively display a struct and its nested pointer fields.

    Runs 'dt -r<depth>' to expand nested structs and follow pointers automatically.
    Great for inspecting complex data structures without manual pointer chasing.

    Args:
        type_name: Type name (e.g. 'module!MyClass', 'ntdll!_PEB')
        address: Memory address of the instance
        depth: Recursion depth for nested structs (default 2, max 5)
    """
    cdb = _require_session()
    d = min(depth, 5)
    result = await cdb.execute(f"dt -r{d} {type_name} {address}")
    return result.output


@mcp.tool()
async def dereference_pointer(address: str) -> str:
    """Read a pointer at an address and show what it points to.

    Displays the pointer value and attempts to show the target as both
    raw memory and a symbol if possible.

    Args:
        address: Address containing the pointer to dereference
    """
    cdb = _require_session()
    ptr_result = await cdb.execute(f"dps {address} L1")
    return ptr_result.output


@mcp.tool()
async def inspect_object(address: str, type_name: str = "") -> str:
    """Inspect a C++ object at an address — shows vtable, fields, and type info.

    If type_name is provided, casts the address to that type.
    Otherwise attempts to identify the type from the vtable.

    Args:
        address: Memory address of the object
        type_name: Optional type to cast to (e.g. 'module!MyClass')
    """
    cdb = _require_session()
    parts = []

    dps = await cdb.execute(f"dps {address} L8")
    parts.append(f"=== Memory (with symbols) ===\n{dps.output}")

    if type_name:
        dt = await cdb.execute(f"dt {type_name} {address}")
        parts.append(f"\n=== Type Layout ===\n{dt.output}")

    return "\n".join(parts)


# ── Variable editing ───────────────────────────────────────────────

@mcp.tool()
async def write_memory(address: str, values: str, format: str = "bytes") -> str:
    """Write values to memory at an address. Use for editing variables, struct fields, etc.

    Args:
        address: Memory address or symbol (e.g. '0x7ff...', 'myapp!g_counter', '$!localVar')
        values: Space-separated values to write (e.g. '0x42', '1 2 3 4', '0n100')
        format: 'bytes' (eb), 'words' (ew), 'dwords' (ed), 'qwords' (eq),
                'ascii' (ea), 'unicode' (eu), 'float' (ef), 'double' (eD)
    """
    cdb = _require_session()
    fmt_map = {
        "bytes": "eb", "words": "ew", "dwords": "ed", "qwords": "eq",
        "ascii": "ea", "unicode": "eu", "float": "ef", "double": "eD",
    }
    cmd_prefix = fmt_map.get(format, "eb")
    result = await cdb.execute(f"{cmd_prefix} {address} {values}")
    return result.output or f"Wrote to {address}"


@mcp.tool()
async def set_variable(name: str, value: str) -> str:
    """Set a local or global variable to a new value.

    For local variables, prefix with $! (e.g. '$!myLocal').
    For globals, use module-qualified names (e.g. 'myapp!g_counter').

    Args:
        name: Variable name (e.g. '$!count', 'myapp!g_flag')
        value: New value as a C++ expression
    """
    cdb = _require_session()
    result = await cdb.execute(f"ed {name} {value}")
    verify = await cdb.execute(f"?? {name}")
    return f"{result.output}\nNew value: {verify.output}"


@mcp.tool()
async def set_register(register: str, value: str) -> str:
    """Set a CPU register to a new value.

    Args:
        register: Register name (e.g. 'rax', 'rcx', 'rip', 'eflags')
        value: New value (hex or decimal with 0n prefix)
    """
    cdb = _require_session()
    result = await cdb.execute(f"r {register}={value}")
    verify = await cdb.execute(f"r {register}")
    return f"{result.output}\n{verify.output}"


# ── Search ──────────────────────────────────────────────────────────

@mcp.tool()
async def search_symbol(pattern: str) -> str:
    """Search for symbols matching a wildcard pattern.

    Args:
        pattern: Wildcard pattern (e.g. 'module!*Create*', '*!main')
    """
    cdb = _require_session()
    result = await cdb.execute(f"x {pattern}")
    return result.output


# ── Exception handling ──────────────────────────────────────────────

@mcp.tool()
async def set_exception_filter(event: str, action: str = "second_chance") -> str:
    """Configure how the debugger handles a specific exception or event.

    Defaults are already set for a good debugging experience:
      - Most exceptions: second-chance only (sxd)
      - Access violations: first-chance break (sxe)
      - C++ exceptions (eh): ignored
      - Invalid handles (ch): ignored

    Args:
        event: Exception code or name. Common ones:
               'av' = access violation, 'eh' = C++ exception,
               'ch' = invalid handle, '*' = all exceptions
        action: How to handle it:
                'break' (sxe) = break on first chance
                'second_chance' (sxd) = only break if unhandled
                'print' (sxn) = print but don't break
                'ignore' (sxi) = fully ignore
    """
    cdb = _require_session()
    action_map = {
        "break": "sxe", "first_chance": "sxe",
        "second_chance": "sxd",
        "print": "sxn",
        "ignore": "sxi",
    }
    cmd = action_map.get(action, "sxd")
    result = await cdb.execute(f"{cmd} {event}")
    return result.output or f"Exception filter set: {cmd} {event}"


# ── Raw command (escape hatch) ──────────────────────────────────────

@mcp.tool()
async def cdb_command(command: str, timeout: float = 30.0) -> str:
    """Execute a raw cdb/WinDbg command. Use this for any command not covered by other tools.

    Args:
        command: The raw cdb command to execute (e.g. '!peb', '.formats 0x1234', '!heap -s')
        timeout: Max seconds to wait for the command to complete
    """
    cdb = _require_session()
    result = await cdb.execute(command, timeout=timeout)
    return result.output


# ── Server entry point ──────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
