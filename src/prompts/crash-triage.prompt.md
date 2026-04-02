# Crash Dump Triage

You are triaging a crash dump (.dmp file) to determine the root cause.
Follow this systematic workflow.

## Step 1: Open the Dump

```
open_dump(path='<dump_file>', symbol_path='<pdb_directory>')
```

## Step 2: Get the Crash Summary

Run these in sequence:

1. `analyze_crash(verbose=True)` — automatic analysis, shows faulting instruction,
   exception type, and likely cause
2. `exception_record()` — raw exception details (access violation address, etc.)

## Step 3: Examine the Faulting Thread

1. `callstack(depth=30)` — full callstack of the crashing thread
2. For each frame that's in YOUR code:
   - `switch_frame(N)` — select that frame
   - `locals()` — check variable values
   - `evaluate('suspiciousVar')` — drill into specific values
   - `display_type('module!Type', address)` — inspect struct contents

## Step 4: Check Other Threads

1. `callstack(all_threads=True)` — see what every thread was doing
2. Look for threads that might have corrupted shared state
3. `switch_thread(N)` + `callstack()` for suspicious threads

## Step 5: Inspect Memory

If the crash is an access violation:
- `read_memory(faulting_address)` — is the memory valid?
- `dereference_pointer(address)` — what does the pointer point to?
- `display_type_recursive('module!Type', address, depth=3)` — follow the object graph

## Step 6: Write a Report

Summarize:
- **What crashed**: Function name, module, source file + line if available
- **Exception type**: Access violation (read/write), stack overflow, etc.
- **Root cause**: What went wrong (null pointer, use-after-free, buffer overflow, etc.)
- **Evidence**: Key variable values, callstack frames, memory state
- **Fix suggestion**: What code change would prevent this
