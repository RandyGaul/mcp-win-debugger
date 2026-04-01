# mcp-win-debugger

An MCP server that gives AI agents native Windows debugging superpowers via CDB (Console Debugger).

## The Problem

The default debugging loop for native code is painfully slow:

```
add print statement → recompile → relaunch → reproduce bug → close app → read logs → repeat
```

Each iteration takes minutes. For large C++ projects, a single recompile can take 10+ minutes.

## The Solution

This MCP server lets an AI agent **debug your process directly** — set breakpoints, inspect memory, read variables, step through code, and even modify state at runtime. No recompilation needed.

```
attach to process → set breakpoint → inspect callstack → read locals → follow pointers → find bug
```

Each operation takes **milliseconds**. The agent navigates the program's live state exactly like you would in Visual Studio, but driven by AI that can cross-reference the source code with what it sees in memory.

## Example: Agent Finds an Off-By-One Bug

Consider this C code with a subtle bug — `get_last_player` returns `&players[count]` instead of `&players[count-1]`:

```c
typedef struct {
    Player* players;
    int count;
    int capacity;
} GameState;

// BUG: off-by-one — accesses players[count] instead of players[count-1]
Player* get_last_player(GameState* game) {
    return &game->players[game->count];  // should be count - 1
}

void apply_poison(GameState* game) {
    Player* last = get_last_player(game);  // reads garbage when count == 0
    damage_player(last, 5);
}
```

The agent launches the program, sets breakpoints, and investigates:

| # | Agent Action | MCP Tool | What the Agent Sees | Conclusion |
|---|-------------|----------|-------------------|------------|
| 1 | Launch with symbols | `launch` | Process started in 0.25s | Ready to debug |
| 2 | Load only our PDB | `load_symbols_for` | `crashme!main`, `crashme!get_last_player` found | Symbols loaded in 0.01s |
| 3 | Break on suspect function | `set_breakpoint` | `bp crashme!get_last_player` — resolved | Breakpoint set |
| 4 | Run the program | `go` | Breakpoint hit instantly | Called from `main+0x8b` |
| 5 | Who called this? | `callstack` | `get_last_player` ← `main` ← `__scrt_common_main_seh` | Normal call from main |
| 6 | What's the game state? | `display_type` | `count: 3, capacity: 4, players: 0x1d7...` | 3 players exist, looks OK |
| 7 | What does it return? | `step_out` + `locals` | `last = 0x00000000'00000000` (NULL!) | Returned bad pointer! |
| 8 | Continue to second call | `go` | Hit BP in `apply_poison` | Second call site |
| 9 | Step into, inspect | `step_into` + `evaluate` | `game->count = 0` | **BUG**: `&players[0]` on empty game = uninitialized memory |

**Root cause found in ~1 second of debug time.** No print statements. No recompilation. The agent read the source, set targeted breakpoints, and followed the data to the bug — the same way you would in Visual Studio, but without the manual clicking.

## Quick Start

### Prerequisites

- **Windows** with [Windows SDK Debugging Tools](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/) installed (provides `cdb.exe`)
- **Python 3.12+** and [uv](https://docs.astral.sh/uv/)

### Install

```bash
git clone https://github.com/RandyGaul/mcp-win-debugger.git
cd mcp-win-debugger
uv sync
```

### Configure Claude Code

Add to your project's `.claude/settings.json`:

```json
{
  "mcpServers": {
    "windbg": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/mcp-win-debugger", "windbg-mcp"]
    }
  }
}
```

### Usage

Tell Claude to debug your program:

> "Launch `D:/build/myapp.exe` with symbols from `D:/build/` and investigate why the player health goes negative"

The agent will:
1. Launch your executable under the debugger
2. Load only YOUR symbols (fast — skips all dependency PDBs)
3. Set breakpoints on relevant functions
4. Run the program, inspect state at breakpoints
5. Follow pointer chains, read structs, check array bounds
6. Identify the root cause

## Tools (39)

### Session Management
| Tool | Description |
|------|-------------|
| `launch` | Launch an executable under the debugger |
| `attach` | Attach to a running process by PID |
| `open_dump` | Open a crash dump (.dmp) for post-mortem analysis |
| `detach` | End the debug session |

### Execution Control
| Tool | Description |
|------|-------------|
| `go` | Continue execution (F5) |
| `step_into` | Step into next instruction (F11) |
| `step_over` | Step over next instruction (F10) |
| `step_out` | Step out of current function (Shift+F11) |
| `break_execution` | Break into running process (Ctrl+Break) |

### Breakpoints
| Tool | Description |
|------|-------------|
| `set_breakpoint` | Set a code breakpoint on a function or address |
| `set_data_breakpoint` | Set a hardware watchpoint on a memory address |
| `list_breakpoints` | List all breakpoints |
| `delete_breakpoint` | Delete a breakpoint by ID |
| `enable_breakpoint` | Enable a disabled breakpoint |
| `disable_breakpoint` | Disable without deleting |

### Inspection
| Tool | Description |
|------|-------------|
| `callstack` | Get call stack (current or all threads) |
| `locals` | Show local variables in current scope |
| `evaluate` | Evaluate a C++ expression |
| `display_type` | Show struct/class layout or instance |
| `display_type_recursive` | Recursively expand nested structs |
| `read_memory` | Read raw memory (bytes, words, qwords, ascii) |
| `dereference_pointer` | Follow a pointer and show target |
| `inspect_object` | Show vtable + fields of a C++ object |

### Modification
| Tool | Description |
|------|-------------|
| `write_memory` | Write values to memory |
| `set_variable` | Set a local or global variable |
| `set_register` | Set a CPU register |

### Navigation
| Tool | Description |
|------|-------------|
| `threads` | List all threads |
| `switch_thread` | Switch to a different thread |
| `switch_frame` | Switch to a different stack frame |

### Symbols
| Tool | Description |
|------|-------------|
| `modules` | List loaded modules |
| `set_symbol_path` | Set symbol search path (with optional cache) |
| `reload_symbols` | Force reload symbols |
| `load_symbols_for` | Load symbols for ONE specific module (fast) |
| `search_symbol` | Search for symbols by wildcard pattern |
| `noisy_symbol_loading` | Toggle verbose symbol diagnostics |

### Analysis
| Tool | Description |
|------|-------------|
| `analyze_crash` | Run `!analyze -v` automatic crash analysis |
| `exception_record` | Show current exception details |
| `set_exception_filter` | Configure which exceptions break vs. are ignored |

### Escape Hatch
| Tool | Description |
|------|-------------|
| `cdb_command` | Run any raw CDB/WinDbg command |

## Guided Workflows (MCP Prompts)

The server includes three guided workflows that agents can follow:

- **`live_debug`** — Step-by-step investigation of a live process
- **`crash_triage`** — Systematic crash dump analysis
- **`memory_corruption`** — Finding memory corruption with data breakpoints

## Performance

The server is optimized for speed:

- **No symbols by default** — empty `-y ""` prevents slow symbol server lookups
- **`-snul`** — disables unqualified symbol loading (massive speedup for large projects)
- **`.symopt+0x100`** — `SYMOPT_NO_UNQUALIFIED_LOADS` at runtime
- **Exception noise suppressed** — `sxd *; sxe av; sxi eh; sxi ch` (only access violations break)
- **Selective symbol loading** — `load_symbols_for('mymodule')` loads one PDB, not everything

| Operation | Time |
|-----------|------|
| Launch small binary | ~0.3s |
| Load one module's symbols | ~0.01s |
| Callstack | <1ms |
| Step over | <1ms |
| Read memory | <1ms |
| Evaluate expression | <1ms |

## Building Test Fixtures

```bash
cd tests/fixtures
cmake -B build
cmake --build build
```

## Running Tests

```bash
uv run pytest tests/ -v
```

Tests share a single CDB session per module for speed (~2.5 min total).

## Architecture

```
Claude Code ←→ MCP (stdio/JSON-RPC) ←→ Python server ←→ cdb.exe (subprocess)
                                              ↕
                                     background reader thread
                                     (readline from stdout pipe)
                                              ↕
                                     echo marker detection
                                     (deterministic command completion)
```

The server manages `cdb.exe` as a subprocess with:
- **Background reader thread** — reads stdout line-by-line (avoids Windows pipe buffering deadlocks)
- **Echo marker protocol** — sends `.echo __MARKER__` after each command for reliable completion detection
- **atexit cleanup** — kills orphaned cdb processes on server exit

## License

This is free and unencumbered software released into the public domain.
See [UNLICENSE](UNLICENSE) for details.
