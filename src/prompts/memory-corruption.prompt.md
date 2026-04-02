# Memory Corruption Investigation

You are investigating a memory corruption bug — data is being overwritten
unexpectedly. This requires a systematic approach using data breakpoints.

## Strategy

Memory corruption means something wrote to memory it shouldn't have.
The key tool is **data breakpoints** (hardware watchpoints) that trigger
when a specific memory address is written to.

## Step 1: Reproduce and Identify the Victim

1. Launch the target: `launch(exe, symbol_path='<pdb_dir>')`
2. Load your symbols: `load_symbols_for('mymodule')`
3. Set a breakpoint where the corruption is DETECTED (not caused):
   `set_breakpoint('mymodule!FunctionThatSeesCorruption')`
4. `go()` — run to that point
5. Inspect the corrupted data:
   - `locals()` — find the corrupted variable
   - `display_type('mymodule!MyStruct', address)` — see the struct fields
   - Note the ADDRESS of the corrupted field

## Step 2: Set a Data Breakpoint

Now you know WHAT got corrupted. Restart and catch WHO does it:

1. `detach()` then re-launch
2. Set a data breakpoint on the corrupted address:
   `set_data_breakpoint(address, size=4, access='w')`
   - size: 1/2/4/8 bytes matching the field size
   - access: 'w' for write (most common), 'rw' for read+write
3. `go()` — the debugger will break the INSTANT something writes to that address

## Step 3: Catch the Corruptor

When the data breakpoint fires:
1. `callstack()` — WHO is writing here?
2. `locals()` — WHAT are they writing and WHY?
3. `evaluate('expression')` — check array indices, pointer arithmetic
4. Cross-reference with source code — is this an off-by-one? Buffer overflow?
   Use-after-free? Wrong pointer?

## Step 4: Verify the Fix

Once you identify the bug:
1. `write_memory(address, correct_values)` — patch the corruption manually
2. `go()` — does the program continue correctly with the patched data?
3. If yes, the fix is confirmed — the corruption at that address was the issue

## Common Corruption Patterns

- **Buffer overflow**: Array write exceeds bounds, overwriting adjacent struct fields
- **Use-after-free**: Pointer to freed memory, now reallocated for something else
- **Double free**: Memory freed twice, corrupts heap metadata
- **Off-by-one**: `array[count]` instead of `array[count-1]`
- **Stack corruption**: Local buffer overflow overwrites return address
- **Type confusion**: Casting to wrong type, fields don't align

## Hardware Breakpoint Limits

x86/x64 has only 4 hardware debug registers (DR0-DR3), so you can set
at most 4 data breakpoints simultaneously. Choose wisely.
