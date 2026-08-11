"""Small formatting helpers for generated public Markdown files."""

from __future__ import annotations

import re


_BLOCK_START = re.compile(
    r"^(?:#{1,6}\s|>|[-+*]\s|\d+[.)]\s|\||-{3,}\s*$|_{3,}\s*$|\*{3,}\s*$|<[^>]+>)"
)
_LIST_START = re.compile(r"^(?:[-+*]\s|\d+[.)]\s)")


def unwrap_prose(text: str) -> str:
    """Join source-level prose wrapping while preserving Markdown blocks."""
    output: list[str] = []
    paragraph: list[str] = []
    in_fence = False

    def flush_paragraph() -> None:
        if paragraph:
            output.append(" ".join(part.strip() for part in paragraph))
            paragraph.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush_paragraph()
            output.append(line)
            in_fence = not in_fence
            continue

        if in_fence:
            output.append(line)
            continue

        if not stripped:
            flush_paragraph()
            if output and output[-1] != "":
                output.append("")
            continue

        if line.startswith("    ") or line.startswith("\t") or _BLOCK_START.match(stripped):
            flush_paragraph()
            output.append(line)
            continue

        if not paragraph and output and output[-1] and _LIST_START.match(output[-1].lstrip()):
            output[-1] += " " + stripped
        else:
            paragraph.append(stripped)

    flush_paragraph()
    while output and output[-1] == "":
        output.pop()
    return "\n".join(output) + "\n"
