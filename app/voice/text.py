"""Spoken-text hygiene for the voice channel.

The system prompt (`app/agent/prompts.PERSONA`) already tells the model to speak in short
sentences with no markdown, so this is belt-and-suspenders: a deterministic post-LLM
scrub applied to every text chunk on its way to TTS (`SpokenTextSanitizer` in
`app/voice/processors.py`). It strips things that sound wrong when read aloud —
markdown emphasis/heading/code markers, `[label](url)` links (kept as just the label),
bare URLs, and leading bullet/`-`/number-list markers.

Kept as a plain pure function (no Pipecat import) so it is unit-testable offline; the
processor wrapper lives in `app/voice/processors.py`.
"""

from __future__ import annotations

import re

# [label](https://…) -> label   (say the words, never the URL)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]*)\)")
# bare URLs
_URL = re.compile(r"(?:https?://|www\.)\S+")
# markdown emphasis / heading / code / blockquote markers
_MD_MARKS = re.compile(r"[*_`#>~]+")
# leading list markers at the start of a line: "- ", "* ", "• ", "1. "
_LIST_MARKER = re.compile(r"(?m)^[ \t]*(?:[-*•]|\d+[.)])[ \t]+")
_MULTISPACE = re.compile(r"[ \t]{2,}")


def sanitize_for_speech(text: str) -> str:
    """Return `text` with markdown/URLs/list markers removed for clean TTS.

    Idempotent and cheap; safe to apply per streamed token chunk. It never adds or
    reorders words — only removes symbols that would be mispronounced.
    """
    if not text:
        return text
    out = _MD_LINK.sub(r"\1", text)
    out = _URL.sub("", out)
    out = _LIST_MARKER.sub("", out)
    out = _MD_MARKS.sub("", out)
    out = _MULTISPACE.sub(" ", out)
    return out
