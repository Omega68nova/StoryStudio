from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


OPEN = "<ss-tool>"
CLOSE = "</ss-tool>"


@dataclass
class InlineToolError:
    code: str
    explanation: str
    offending_fields: list[str]
    correction_hint: str

    def payload(self, tool_name: str = "") -> dict[str, Any]:
        return {
            "tool_name": tool_name,
            "error_code": self.code,
            "explanation": self.explanation,
            "offending_fields": self.offending_fields,
            "safe_correction_hints": [self.correction_hint],
        }


class InlineToolParser:
    """Incrementally removes StoryStudio tool envelopes from a text stream."""

    def __init__(self, max_envelope_chars: int = 32_768) -> None:
        self.buffer = ""
        self.inside = False
        self.max_envelope_chars = max_envelope_chars

    def feed(self, chunk: str) -> tuple[str, list[dict[str, Any]], list[InlineToolError]]:
        self.buffer += chunk
        visible: list[str] = []
        tools: list[dict[str, Any]] = []
        errors: list[InlineToolError] = []
        while self.buffer:
            if not self.inside:
                marker = self.buffer.find(OPEN)
                if marker >= 0:
                    visible.append(self.buffer[:marker])
                    self.buffer = self.buffer[marker + len(OPEN):]
                    self.inside = True
                    continue
                keep = self._partial_suffix(self.buffer, OPEN)
                if keep:
                    visible.append(self.buffer[:-keep])
                    self.buffer = self.buffer[-keep:]
                else:
                    visible.append(self.buffer)
                    self.buffer = ""
                break
            marker = self.buffer.find(CLOSE)
            if marker < 0:
                if len(self.buffer) > self.max_envelope_chars:
                    errors.append(InlineToolError(
                        "envelope_too_large", "The inline action exceeded the size limit.", [],
                        "Use one concise action with literal JSON values.",
                    ))
                    self.buffer = ""
                    self.inside = False
                break
            raw = self.buffer[:marker]
            self.buffer = self.buffer[marker + len(CLOSE):]
            self.inside = False
            try:
                values = self._decode_values(raw)
                for value in values:
                    if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not isinstance(value.get("arguments", {}), dict):
                        raise ValueError("name must be a string and arguments must be an object")
                    tools.append({"name": value["name"], "arguments": value.get("arguments", {})})
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(InlineToolError(
                    "malformed_envelope", f"Invalid inline action JSON: {exc}", ["name", "arguments"],
                    'Emit exactly <ss-tool>{"name":"toolName","arguments":{}}</ss-tool>.',
                ))
        return "".join(visible), tools, errors

    @staticmethod
    def _decode_values(raw: str) -> list[Any]:
        """Decode one or more adjacent actions and tolerate hidden trailing commentary.

        Local models sometimes omit the close marker between two envelopes, or
        place a short explanation after a valid JSON object. The valid leading
        action remains schema-validated by the scheduler; non-JSON text stays
        hidden instead of forcing a costly repair completion.
        """
        source = raw.strip()
        if source.startswith("```json"):
            source = source[7:].strip()
        elif source.startswith("```"):
            source = source[3:].strip()
        if source.endswith("```"):
            source = source[:-3].rstrip()
        decoder, values = json.JSONDecoder(), []
        while source:
            value, end = decoder.raw_decode(source)
            values.append(value)
            source = source[end:].lstrip()
            if source.startswith(","):
                source = source[1:].lstrip()
            if source and not source.startswith("{"):
                break
        if not values:
            raise json.JSONDecodeError("No inline action object", raw, 0)
        return values

    def finish(self) -> tuple[str, list[InlineToolError]]:
        if self.inside:
            self.buffer = ""
            self.inside = False
            return "", [InlineToolError(
                "unterminated_envelope", "The inline action was not closed.", [],
                f"Close every action with {CLOSE}.",
            )]
        visible, self.buffer = self.buffer, ""
        return visible, []

    @staticmethod
    def _partial_suffix(value: str, marker: str) -> int:
        for size in range(min(len(value), len(marker) - 1), 0, -1):
            if value.endswith(marker[:size]):
                return size
        return 0
