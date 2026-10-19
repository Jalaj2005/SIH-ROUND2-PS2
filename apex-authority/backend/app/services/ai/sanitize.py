"""Handling of untrusted text (instructor free text, trainee rationales, report content).

Defence in depth: (1) bounded, cleaned input; (2) injection phrases are *flagged* for the instructor;
(3) data is passed to the model only inside a JSON block with angle brackets escaped so it cannot
close the delimiter; (4) the system prompt declares the block to be data; (5) model output is
re-validated and server-controlled fields (id/status/scores) are never taken from it.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

UNTRUSTED_OPEN = "<untrusted_input>"
UNTRUSTED_CLOSE = "</untrusted_input>"

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
    r"disregard (all |any |the )?(previous|prior|above|earlier)",
    r"(reveal|print|show|output|repeat).{0,30}(system prompt|instructions|api key|secret|credentials)",
    r"you are now\b",
    r"\bnew instructions?\b",
    r"(set|mark|change).{0,20}status.{0,15}(approved|archived)",
    r"\bapprove (this|the) scenario\b",
    r"(start|activate|launch) (the |a )?session",
    r"</?(system|untrusted_input|assistant|user)>",
    r"\bjailbreak\b",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _INJECTION_PATTERNS]


def clean_text(value: str, max_len: int = 2000) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = _CONTROL.sub("", value)
    value = re.sub(r"[ \t]+", " ", value).strip()
    return value[:max_len]


def clean_obj(obj: Any, max_len: int = 2000) -> Any:
    if isinstance(obj, str):
        return clean_text(obj, max_len)
    if isinstance(obj, list):
        return [clean_obj(o, max_len) for o in obj]
    if isinstance(obj, dict):
        return {str(k)[:100]: clean_obj(v, max_len) for k, v in obj.items()}
    return obj


def _strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for o in obj:
            yield from _strings(o)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)


def detect_injection(obj: Any) -> list[str]:
    """Return the field-agnostic list of matched patterns (for instructor-facing warnings)."""
    hits: list[str] = []
    for s in _strings(obj):
        for rx in _INJECTION_RE:
            if rx.search(s) and rx.pattern not in hits:
                hits.append(rx.pattern)
    return hits


def untrusted_block(obj: Any) -> str:
    """Serialise to JSON with '<' and '>' escaped so the content can never terminate the block."""
    dumped = json.dumps(obj, ensure_ascii=False, indent=1, default=str)
    dumped = dumped.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"{UNTRUSTED_OPEN}\n{dumped}\n{UNTRUSTED_CLOSE}"


_BLOCK_RE = re.compile(re.escape(UNTRUSTED_OPEN) + r"\n(.*?)\n" + re.escape(UNTRUSTED_CLOSE), re.DOTALL)


def extract_untrusted_blocks(prompt: str) -> list[Any]:
    """Used by the fixture provider/tests to read the data back out of a prompt."""
    return [json.loads(m) for m in _BLOCK_RE.findall(prompt)]
