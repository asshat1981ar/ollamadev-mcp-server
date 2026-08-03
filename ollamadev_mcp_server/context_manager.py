"""Context window management for LLM prompts.

Provides intelligent context assembly that respects token budgets while
preserving the most important information.  Uses priority-based assembly
and smart truncation at natural boundaries.

Usage::

    from ollamadev_mcp_server.context_manager import ContextWindow

    window = ContextWindow(total_budget=4096)
    window.add_section("goal", "Fix authentication bug", priority=100)
    window.add_section("history", "...", priority=50)
    context = window.assemble()
"""

import re
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Approximate token-to-character ratio (English text ≈ 4 chars/token)
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count for text.

    Uses a simple character-based heuristic.  For more accurate counting,
    consider using tiktoken or the model's tokenizer.
    """
    return len(text) // CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# Context window
# ---------------------------------------------------------------------------


class ContextWindow:
    """Manages a context window with budget-aware assembly.

    Attributes:
        total_budget: Maximum token budget for the assembled context.
    """

    def __init__(self, total_budget: int = 4096):
        self.total_budget = total_budget
        self.sections: dict[str, str] = {}
        self.priorities: dict[str, int] = {}

    def add_section(self, name: str, content: str, priority: int = 0) -> None:
        """Add a section to the context window.

        Args:
            name: Section name (e.g., "goal", "history").
            content: Section content.
            priority: Higher priority sections are kept first when truncating.
        """
        self.sections[name] = content
        self.priorities[name] = priority

    def assemble(self) -> str:
        """Assemble sections within budget, respecting priorities.

        Returns:
            Assembled context string with sections separated by blank lines.
        """
        # Sort by priority (highest first)
        sorted_sections = sorted(
            self.sections.items(),
            key=lambda x: self.priorities.get(x[0], 0),
            reverse=True,
        )

        parts: list[str] = []
        used_tokens = 0

        for name, content in sorted_sections:
            content_tokens = estimate_tokens(content)
            if used_tokens + content_tokens <= self.total_budget:
                parts.append(f"## {name}\n{content}")
                used_tokens += content_tokens
            else:
                # Try to fit a truncated version
                remaining = self.total_budget - used_tokens
                if remaining >= 10:  # Minimum useful content (10 tokens = 40 chars)
                    truncated = self._truncate_smart(content, remaining * CHARS_PER_TOKEN)
                    parts.append(f"## {name} (truncated)\n{truncated}")
                    used_tokens += remaining
                    logger.debug(
                        "Truncated section '%s' from %d to %d chars",
                        name,
                        len(content),
                        len(truncated),
                    )
                break

        return "\n\n".join(parts)

    def _truncate_smart(self, text: str, max_chars: int) -> str:
        """Truncate text at a natural boundary (line, sentence, or word).

        Args:
            text: Text to truncate.
            max_chars: Maximum character count.

        Returns:
            Truncated text with ellipsis if truncated.
        """
        if len(text) <= max_chars:
            return text

        # Try to truncate at a line boundary
        truncated = text[:max_chars]
        last_newline = truncated.rfind("\n")
        if last_newline > max_chars * 0.5:
            return truncated[:last_newline] + "\n..."

        # Try to truncate at a sentence boundary
        last_sentence = max(
            truncated.rfind(". "),
            truncated.rfind(".\n"),
            truncated.rfind("! "),
            truncated.rfind("? "),
        )
        if last_sentence > max_chars * 0.5:
            return truncated[: last_sentence + 1] + "..."

        # Fall back to word boundary
        last_space = truncated.rfind(" ")
        if last_space > max_chars * 0.5:
            return truncated[:last_space] + "..."

        return truncated[: max_chars - 3] + "..."


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def build_suggestion_context(
    goal: str,
    phase: str,
    tool_results: list[dict[str, Any]],
    tool_catalog: str,
    max_tokens: int = 4096,
) -> str:
    """Build context for the suggest_next_action prompt.

    Args:
        goal: Sprint goal.
        phase: Current sprint phase.
        tool_results: Recent tool call results.
        tool_catalog: Tool catalog markdown.
        max_tokens: Maximum token budget.

    Returns:
        Assembled context string.
    """
    window = ContextWindow(total_budget=max_tokens)

    # High priority: goal and phase
    window.add_section("Sprint Goal", goal, priority=100)
    window.add_section("Current Phase", phase, priority=90)

    # Medium priority: recent tool results
    if tool_results:
        results_text = "\n".join(
            f"- {r['tool_name']}: {r.get('text', r.get('error', ''))[:200]}"
            for r in tool_results[-5:]
        )
        window.add_section("Recent Actions", results_text, priority=50)

    # Lower priority: tool catalog
    window.add_section("Available Tools", tool_catalog, priority=10)

    return window.assemble()


def format_tool_result_for_context(
    tool_name: str,
    result: str,
    max_chars: int = 500,
) -> str:
    """Format a tool result for inclusion in context.

    Args:
        tool_name: Name of the tool.
        result: Tool result string.
        max_chars: Maximum character count for the result.

    Returns:
        Formatted string like "[tool_name] result_preview".
    """
    # Try to extract the most useful part
    # For JSON results, try to extract key fields
    import json

    try:
        data = json.loads(result)
        if isinstance(data, dict):
            summary_parts = []
            for key in ("status", "error", "summary", "message"):
                if key in data:
                    summary_parts.append(f"{key}={data[key]}")
            if summary_parts:
                return f"[{tool_name}] {', '.join(summary_parts)}"
    except (json.JSONDecodeError, TypeError):
        pass

    # Fall back to full result or truncated
    if len(result) <= max_chars:
        return f"[{tool_name}] {result}"
    return f"[{tool_name}] {result[:max_chars]}..."
