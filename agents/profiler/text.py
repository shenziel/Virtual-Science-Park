"""Text handling for the profiler: HTML to text, sentences, verbatim checks.

Standard library only, so the profiler adds no dependency (AGENTS.md §3).

The rule that matters here: a ``stated`` claim must quote the page *verbatim*.
``is_verbatim`` is what lets the profiler reject a quote the model made up
instead of trusting it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_WS = re.compile(r"\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_LIST_PREFIX = re.compile(r"^(?:[\u2022\u00b7\-*\u2013\u2014]|\d+[.)])\s+")


@dataclass(frozen=True)
class Document:
    """Readable text of a page, plus the hints that usually describe the company."""

    text: str
    title: str = ""
    description: str = ""

    def sentences(self, min_chars: int = 20) -> list[str]:
        return sentences(self.text, min_chars=min_chars)


class _Extractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "canvas"}
    BLOCK = {
        "p", "div", "li", "ul", "ol", "br", "tr", "td", "th", "table",
        "section", "article", "header", "footer", "main", "nav", "aside",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "figure", "form",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._title: list[str] = []
        self._in_title = False
        self.description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            attr = {k.lower(): (v or "") for k, v in attrs}
            name = (attr.get("name") or attr.get("property") or "").lower()
            content = attr.get("content") or ""
            if content and name in {"description", "og:description", "twitter:description"}:
                self.description = self.description or content
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title.append(data)
            return
        self.parts.append(data)


def html_to_document(html: str) -> Document:
    """Strip markup and scripts, keep readable text plus title/description."""
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed HTML is common, not fatal
        pass
    text = _clean_block("".join(parser.parts))
    return Document(
        text=text,
        title=collapse(" ".join(parser._title)),
        description=collapse(parser.description),
    )


def collapse(value: str) -> str:
    return _WS.sub(" ", value or "").strip()


def _clean_block(raw: str) -> str:
    lines = [collapse(line) for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def sentences(text: str, min_chars: int = 20) -> list[str]:
    """Split readable text into candidate quote-sized sentences."""
    out: list[str] = []
    for line in text.splitlines():
        for part in _SENTENCE_SPLIT.split(line):
            part = _LIST_PREFIX.sub("", collapse(part))
            if len(part) >= min_chars:
                out.append(part)
    return out


def is_verbatim(snippet: str | None, text: str) -> bool:
    """True when ``snippet`` appears in ``text`` word for word (case-insensitive)."""
    needle = collapse(snippet or "").casefold()
    if not needle:
        return False
    return needle in collapse(text).casefold()


def truncate(value: str, limit: int) -> str:
    """Trim to ``limit`` characters on a word boundary."""
    value = collapse(value)
    if len(value) <= limit:
        return value
    cut = value[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "\u2026"


@dataclass
class DropLog:
    """Claims the profiler refused to publish, with the reason (for logging only)."""

    reasons: list[tuple[str, str]] = field(default_factory=list)

    def add(self, value: str, reason: str) -> None:
        self.reasons.append((value[:80], reason))

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return bool(self.reasons)
