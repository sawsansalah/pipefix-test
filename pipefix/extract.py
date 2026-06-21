"""
Extracts just the relevant failure context from a (possibly huge) log,
instead of blindly sending the whole thing or a blind head+tail trim.

Most CI log volume is noise: dependency download progress, passing test
output, build tool banners. The actual signal is usually a small block
around the error. Shrinking what we send to Claude cuts token cost
directly, often by 80-90% on a verbose build.

Strategy:
  1. Use any heuristic classifier matches as anchor points (we already
     know which lines matched a known failure pattern).
  2. Also scan for generic "this looks like an error" markers, in case
     the classifier didn't match anything.
  3. Grab a small context window around each anchor, dedup overlapping
     windows, and join them.
  4. If nothing is found at all, fall back to the last N lines, since
     errors usually surface near the end of a log rather than the start.
"""

import re

CONTEXT_LINES_BEFORE = 3
CONTEXT_LINES_AFTER = 8
MAX_BLOCK_CHARS = 4000  # hard cap on what we ever send, post-extraction
FALLBACK_TAIL_LINES = 80

GENERIC_ERROR_MARKERS = re.compile(
    r"(Traceback \(most recent call last\)|error[:\[]|Error:|FAILED|FAIL\s|"
    r"panicked at|BUILD FAILURE|AssertionError|Exception|"
    r"COPY failed|exit code [1-9])",
    re.IGNORECASE,
)


def _find_anchor_line_numbers(lines: list[str], classification) -> set[int]:
    anchors = set()

    # Anchor on whatever the classifier already matched.
    matched_texts = {m.matched_line for m in classification.matches} if classification else set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped in matched_texts:
            anchors.add(i)
        elif GENERIC_ERROR_MARKERS.search(line):
            anchors.add(i)

    return anchors


def extract_failure_block(log_text: str, classification=None) -> str:
    lines = log_text.splitlines()
    if not lines:
        return log_text

    anchors = _find_anchor_line_numbers(lines, classification)

    if not anchors:
        # Nothing matched anything error-like — fall back to the tail,
        # since that's usually where the actual failure printed.
        tail = lines[-FALLBACK_TAIL_LINES:]
        block = "\n".join(tail)
        return block[-MAX_BLOCK_CHARS:]

    # Build context windows around each anchor and merge overlapping ranges.
    ranges = []
    for a in sorted(anchors):
        start = max(0, a - CONTEXT_LINES_BEFORE)
        end = min(len(lines), a + CONTEXT_LINES_AFTER + 1)
        ranges.append([start, end])

    merged = []
    for r in ranges:
        if merged and r[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], r[1])
        else:
            merged.append(r)

    blocks = []
    for start, end in merged:
        blocks.append("\n".join(lines[start:end]))

    combined = "\n\n[...]\n\n".join(blocks)

    if len(combined) > MAX_BLOCK_CHARS:
        # Trim from the middle, keep the first and last extracted blocks —
        # those are usually the most informative (first failure, final state).
        half = MAX_BLOCK_CHARS // 2
        combined = combined[:half] + "\n\n[... extracted block trimmed ...]\n\n" + combined[-half:]

    return combined
