"""Patch / diff tools for surgical file edits."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import WORKSPACE_ROOT
from ollamadev_mcp_server.tools.filesystem import _safe_path


@dataclass
class Hunk:
    start_line: int  # 0-based line number in original file
    old_lines: list[str]
    new_lines: list[str]


def _parse_patch(patch_text: str) -> list[Hunk]:
    """Parse unified diff text into hunks.

    Returns a list of Hunks, each containing the 0-based start line in the
    original file and the old/new line content (excluding the leading +/- markers).
    """
    hunks: list[Hunk] = []
    current_old: list[str] = []
    current_new: list[str] = []
    current_start = 0
    in_hunk = False

    for raw_line in patch_text.splitlines():
        line = raw_line.rstrip("\n")
        if not line and not in_hunk:
            continue
        if line.startswith("---") or line.startswith("+++") or line.startswith("diff ") or line.startswith("index "):
            continue

        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            if in_hunk:
                hunks.append(Hunk(current_start, current_old, current_new))
            current_start = int(m.group(1)) - 1  # convert to 0-based
            current_old = []
            current_new = []
            in_hunk = True
            continue

        if not in_hunk:
            continue

        if line.startswith(" "):
            text = line[1:]
            current_old.append(text)
            current_new.append(text)
        elif line.startswith("-"):
            current_old.append(line[1:])
        elif line.startswith("+"):
            current_new.append(line[1:])
        elif line == "\\ No newline at end of file":
            # We ignore the no-newline marker for simplicity; still works for most files.
            continue

    if in_hunk and (current_old or current_new):
        hunks.append(Hunk(current_start, current_old, current_new))

    return hunks


def _apply_hunk(lines: list[str], hunk: Hunk, reverse: bool) -> list[str]:
    """Apply a single hunk to a list of lines and return the modified list."""
    old = hunk.new_lines if reverse else hunk.old_lines
    new = hunk.old_lines if reverse else hunk.new_lines

    start = hunk.start_line
    if start < 0 or start + len(old) > len(lines):
        raise RuntimeError(f"Hunk starting at line {start + 1} is out of range")

    # Verify that context lines (lines that appear in both old and new) match the original.
    expected = list(old)
    actual = lines[start:start + len(old)]
    if expected != actual:
        # Show a small preview to help debug.
        preview = "\n".join(f"  {i + start + 1}: {actual[i]}" for i in range(min(5, len(actual))))
        raise RuntimeError(
            f"Hunk at line {start + 1} does not match file content.\nExpected:\n" +
            "\n".join(f"  {l}" for l in expected[:5]) +
            f"\nActual (first lines):\n{preview}"
        )

    # Replace the old slice with the new slice.
    return lines[:start] + new + lines[start + len(old):]


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def apply_file_patch(path: str, patch: str, reverse: bool = False) -> str:
        """Apply a unified-diff style patch to an existing workspace file.

        The patch must contain at least one hunk in unified diff format, e.g.:
          --- a/app/src/main/java/com/example/Foo.kt
          +++ b/app/src/main/java/com/example/Foo.kt
          @@ -10,3 +10,4 @@
           line kept
          -line removed
          +line added
           line kept

        Args:
            path:    Relative path of the file to patch.
            patch:   Unified diff text.
            reverse: Apply the patch in reverse (unapply). Default: False.

        Returns:
            Confirmation message including the number of hunks applied.
        """
        target = _safe_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not target.is_file():
            raise ValueError(f"Path is not a file: {path}")

        # Prefer system `patch` if available for robustness.
        has_patch = subprocess.run(["which", "patch"], capture_output=True, text=True).returncode == 0
        if has_patch:
            cmd = ["patch", str(target)]
            if reverse:
                cmd.append("-R")
            result = subprocess.run(cmd, input=patch, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise RuntimeError(f"patch command failed:\n{result.stderr or result.stdout}")
            return f"Patched {path} using system patch (exit {result.returncode})"

        hunks = _parse_patch(patch)
        if not hunks:
            return "No valid hunks found in patch."

        original_text = target.read_text(encoding="utf-8")
        ends_with_newline = original_text.endswith("\n")
        lines = original_text.splitlines()

        # Apply hunks bottom-up so earlier line numbers remain valid.
        for hunk in reversed(hunks):
            lines = _apply_hunk(lines, hunk, reverse)

        new_text = "\n".join(lines)
        if ends_with_newline:
            new_text += "\n"
        target.write_text(new_text, encoding="utf-8")

        return f"Patched {path} manually ({len(hunks)} hunk(s))"
