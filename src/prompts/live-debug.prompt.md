# Live Debug Investigation

You are debugging a running process using CDB (Console Debugger) via MCP tools.
Your goal is to investigate a bug by inspecting the live state of the program —
exactly like a developer would in Visual Studio, but faster and more systematic.

## Setup Phase

1. **Launch or attach** to the target process:
   - `launch(executable, symbol_path='<dir containing your PDB>')`
   - Or `attach(pid)` for an already-running process

2. **Load symbols** for ONLY the module you care about:
   - `load_symbols_for('mymodule', pdb_path='<dir>')`
   - Use module-qualified names for everything: `mymodule!MyFunction`
   - Do NOT load all symbols — it's slow and unnecessary

3. **Verify symbols loaded**:
   - `search_symbol('mymodule!*')` to see available functions
   - `modules()` to confirm module is listed

## Investigation Loop

Repeat until you find the root cause:

1. **Set breakpoints** at suspicious locations:
   - `set_breakpoint('mymodule!FunctionName')` for code breakpoints
   - `set_data_breakpoint(address, size=4, access='w')` to catch memory writes

2. **Run to breakpoint**: `go()`

3. **Examine state** when stopped:
   - `callstack()` — who called this function and why?
   - `locals()` — what are the current variable values?
   - `evaluate('expression')` — check specific values
   - `display_type('mymodule!MyStruct', address)` — inspect struct contents
   - `display_type_recursive('mymodule!MyClass', address, depth=2)` — follow pointers
   - `read_memory(address, format='qwords')` — raw memory

4. **Navigate**:
   - `step_into()` — follow a function call
   - `step_over()` — execute without entering
   - `step_out()` — run until current function returns
   - `switch_frame(N)` — look at a different stack frame
   - `switch_thread(N)` — check another thread

5. **Modify state** to test hypotheses:
   - `set_variable('$!localVar', 'newValue')` — change a local
   - `write_memory(address, values)` — patch memory
   - `set_register('rax', '0x42')` — change a register

## Key Principles

- **Be surgical**: Only load symbols you need. Use module-qualified names.
- **Read the source**: Cross-reference what you see in the debugger with the source code.
  The source tells you WHAT a variable should be; the debugger tells you what it IS.
- **Follow the data**: Start from the crash/bug site and trace backwards through the
  callstack. At each frame, check if the inputs look correct.
- **Check assumptions**: If a pointer should be non-null, verify it. If an index should
  be in range, check the bounds. If a flag should be set, inspect it.
- **Minimize stepping**: Prefer breakpoints over single-stepping through large functions.
  Set a breakpoint where you think the bug is, not at the top of main.
