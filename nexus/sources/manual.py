"""Plain Markdown/text and non-rendering HTML source adapter."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from ..contracts import SourceType
from ..errors import ParseError
from ..fingerprints import fallback_message_id, sha256_bytes
from ..normalize import NormalizedConversation, NormalizedMessage, normalize_text
from .base import ParsedSource


class _SafeTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


class ManualAdapter:
    name = "manual-text"
    version = "1"
    source_type = SourceType.MANUAL

    def supports(self, path: Path, payload_prefix: bytes) -> bool:
        return path.suffix.lower() in {".md", ".txt", ".html", ".htm"}

    def parse_bytes(self, payload: bytes, *, original_name: str) -> ParsedSource:
        try:
            decoded = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ParseError("manual source must be UTF-8") from exc
        suffix = Path(original_name).suffix.lower()
        if suffix in {".html", ".htm"}:
            extractor = _SafeTextExtractor()
            extractor.feed(decoded)
            decoded = "\n".join(extractor.parts)
        content = normalize_text(decoded)
        if not content:
            raise ParseError("manual source contains no text")
        content_hash = sha256_bytes(content.encode("utf-8"))
        external_id = f"manual:{content_hash}"
        message_id = fallback_message_id(
            source_identity=external_id,
            role="user",
            created_at=None,
            content_sha256=content_hash,
        )
        locator = f"manual:{Path(original_name).name}"
        message = NormalizedMessage.build(
            message_id=message_id,
            role="user",
            content=content,
            source_locator=f"{locator}#message={message_id}",
        )
        conversation = NormalizedConversation(
            external_conversation_id=external_id,
            title=Path(original_name).stem,
            participants=("user",),
            messages=(message,),
            source_locator=locator,
        )
        return ParsedSource(
            source_type=self.source_type,
            adapter_name=self.name,
            adapter_version=self.version,
            original_name=Path(original_name).name,
            conversations=(conversation,),
        )
