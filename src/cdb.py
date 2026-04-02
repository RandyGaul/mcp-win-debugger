"""
cdb.exe process manager.

Spawns cdb.exe via subprocess.Popen and uses a background thread to
read stdout line-by-line (avoids Windows pipe buffering deadlocks).
Command completion is detected via a deterministic echo marker.
"""

import atexit
import asyncio
import logging
import os
import signal
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

COMMAND_MARKER = "__MCP_CMD_DONE__"
LAUNCH_MARKER = "__MCP_LAUNCH_READY__"

CDB_SEARCH_PATHS = [
    r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe",
    r"C:\Program Files\Windows Kits\10\Debuggers\x64\cdb.exe",
    r"D:\tools\debuggers\x64\cdb.exe",
]

_active_sessions: list["CdbProcess"] = []


def _cleanup_all():
    for session in _active_sessions:
        try:
            if session._proc and session._proc.poll() is None:
                session._proc.kill()
        except Exception:
            pass


atexit.register(_cleanup_all)


def find_cdb() -> str:
    env_path = os.environ.get("CDB_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    for path in CDB_SEARCH_PATHS:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "cdb.exe not found. Install Windows SDK Debugging Tools or set CDB_PATH."
    )


@dataclass
class CdbResult:
    command: str
    output: str
    prompt: str = ""


class CdbProcess:
    """Manages a cdb.exe subprocess with a background reader thread."""

    def __init__(self, cdb_path: str | None = None, timeout: float = 60.0):
        self.cdb_path = cdb_path or find_cdb()
        self.timeout = timeout
        self.initial_symbol_path: str | None = None  # Set before launch to control -y flag
        self._proc: subprocess.Popen | None = None
        self._lock = asyncio.Lock()
        self._started = False
        # Reader thread pushes lines into _lines and signals _has_lines
        self._lines: deque[str] = deque()
        self._has_lines = threading.Event()
        self._reader_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def launch(self, args: list[str]) -> CdbResult:
        if self._started:
            raise RuntimeError("cdb session already active — detach or quit first")

        # Build the startup command chain:
        # 1. SYMOPT_NO_UNQUALIFIED_LOADS — prevents auto-loading all module symbols
        # 2. Exception filters — don't break on first-chance noise, only real crashes
        #    sxd * = second-chance only for everything (don't spam on normal exceptions)
        #    sxe av = break immediately on access violations
        #    sxi eh = fully ignore C++ exception machinery
        #    sxi ch = fully ignore invalid handle exceptions
        # 3. Echo marker so we know startup is done
        startup_parts = [
            ".symopt+0x100",
            "sxd *",
            "sxe av",
            "sxi eh",
            "sxi ch",
            f".echo {LAUNCH_MARKER}",
        ]
        startup_cmd = "; ".join(startup_parts)

        cmd = [self.cdb_path]
        # -snul: suppress symbol loading for unqualified names (huge perf win)
        cmd.append("-snul")
        # Default: NO symbols loaded. User sets symbol_path for their own PDB only.
        sym_path = self.initial_symbol_path if self.initial_symbol_path is not None else ""
        cmd.extend(["-y", sym_path])
        cmd.extend(["-c", startup_cmd])
        cmd.extend(args)
        logger.info("Launching: %s", " ".join(cmd))

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = 0x00000200  # CREATE_NEW_PROCESS_GROUP

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        self._started = True
        _active_sessions.append(self)

        # Start background reader
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        # Wait for the launch marker
        output = await asyncio.wait_for(
            self._collect_until_marker(LAUNCH_MARKER),
            timeout=self.timeout,
        )
        return CdbResult(command="<launch>", output=output.strip())

    async def open_dump(self, dump_path: str, symbol_path: str | None = None) -> CdbResult:
        args = ["-z", dump_path]
        if symbol_path:
            args.extend(["-y", symbol_path])
        return await self.launch(args)

    async def launch_executable(self, exe_path: str, exe_args: list[str] | None = None) -> CdbResult:
        args = ["-o", exe_path]
        if exe_args:
            args.extend(exe_args)
        return await self.launch(args)

    async def attach(self, pid: int) -> CdbResult:
        return await self.launch(["-p", str(pid)])

    async def execute(self, command: str, timeout: float | None = None) -> CdbResult:
        if not self.is_running:
            raise RuntimeError("No active cdb session")

        timeout = timeout or self.timeout

        async with self._lock:
            assert self._proc is not None and self._proc.stdin is not None

            logger.debug("Sending: %s", command)
            payload = f"{command}\n.echo {COMMAND_MARKER}\n".encode()
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()

            output = await asyncio.wait_for(
                self._collect_until_marker(COMMAND_MARKER),
                timeout=timeout,
            )

            # Strip echoed command from first line
            lines = output.split("\n")
            if lines and command and command in lines[0]:
                output = "\n".join(lines[1:])

            return CdbResult(command=command, output=output.strip())

    async def quit(self) -> str:
        if not self.is_running:
            self._started = False
            return "No active session"
        try:
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write(b"q\n")
            self._proc.stdin.flush()
            self._proc.wait(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            if self._proc:
                self._proc.kill()
        finally:
            if self in _active_sessions:
                _active_sessions.remove(self)
            self._proc = None
            self._started = False
        return "Session ended"

    async def send_break(self):
        if not self.is_running:
            raise RuntimeError("No active cdb session")
        assert self._proc is not None
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.GenerateConsoleCtrlEvent(1, self._proc.pid)
        else:
            self._proc.send_signal(signal.SIGINT)

    # ── Background reader ───────────────────────────────────────────

    def _reader_loop(self):
        """Read stdout line-by-line in a background thread.

        Uses readline() which works correctly on Windows pipes (unlike
        byte-by-byte read(1) which can block on partial pipe buffers).
        """
        assert self._proc is not None and self._proc.stdout is not None
        stdout = self._proc.stdout

        try:
            while True:
                raw = stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                self._lines.append(line)
                self._has_lines.set()
        except (OSError, ValueError):
            pass

    async def _collect_until_marker(self, marker: str) -> str:
        """Collect lines from the reader thread until the marker appears."""
        loop = asyncio.get_running_loop()
        output_lines: list[str] = []

        while True:
            # Drain all available lines
            while self._lines:
                line = self._lines.popleft()
                if marker in line:
                    return "\n".join(output_lines)
                # Skip the echoed .echo command and cdb's "Reading initial command" lines
                stripped = line.strip()
                if stripped.startswith(f".echo {marker}"):
                    continue
                if "Reading initial command" in line and marker in line:
                    continue
                # Skip any other marker references from prior commands
                if LAUNCH_MARKER in line or COMMAND_MARKER in line:
                    continue
                # Strip cdb prompt prefix (e.g. "0:000> " at start of line)
                import re
                line = re.sub(r"^\d+:\d+(?::\w+)?> ", "", line)
                output_lines.append(line)

            # Wait for the reader thread to signal new lines
            self._has_lines.clear()
            await loop.run_in_executor(None, self._has_lines.wait, self.timeout)
