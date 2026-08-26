"""Deterministic, structure-aware chunking with document context headers."""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from typing import Any

from competition.knowledge_types import KnowledgeChunk, ParsedDocument

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？.!?])\s+|\n{2,}")
_CJK = re.compile(r"[\u3400-\u9fff]")
_NATIVE_SUFFIXES = (".adoc", ".asciidoc", ".csv", ".htm", ".html", ".json", ".md", ".rst", ".text", ".txt")


def estimate_tokens(text: str) -> int:
    cjk = len(_CJK.findall(text))
    remainder = _CJK.sub(" ", text)
    words = len(re.findall(r"\b\w+\b", remainder))
    punctuation = len(re.findall(r"[^\w\s]", remainder))
    return max(1, math.ceil(cjk * 0.75 + words * 1.25 + punctuation * 0.25))


def _split_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    clean = text.strip()
    if len(clean) <= max_chars:
        return [clean] if clean else []
    units = [unit.strip() for unit in _SENTENCE_BOUNDARY.split(clean) if unit.strip()]
    if len(units) == 1:
        units = [clean[index : index + max_chars] for index in range(0, len(clean), max_chars)]
    result: list[str] = []
    buffer = ""
    for unit in units:
        candidate = f"{buffer}\n{unit}".strip() if buffer else unit
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            result.append(buffer)
            overlap = buffer[-overlap_chars:] if overlap_chars else ""
            buffer = f"{overlap}\n{unit}".strip()
        else:
            result.append(unit[:max_chars])
            buffer = unit[max_chars - overlap_chars :]
        while len(buffer) > max_chars:
            result.append(buffer[:max_chars])
            buffer = buffer[max_chars - overlap_chars :]
    if buffer:
        result.append(buffer)
    return result


def build_chunks(
    parsed: ParsedDocument,
    *,
    document: dict[str, Any],
    version_no: int,
    max_chars: int = 2600,
    overlap_chars: int = 240,
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    ordinal = 0
    for block in parsed.blocks:
        for text in _split_text(block.text, max_chars, overlap_chars):
            section = block.section_path or parsed.title
            header_parts = [f"Document: {document.get('title') or parsed.title}"]
            for label, value in (
                ("Product", document.get("product")),
                ("Dimension", document.get("dimension")),
                ("Market", document.get("market_scope")),
                ("Source", document.get("source_uri") or document.get("filename")),
                ("Published", document.get("published_at")),
                ("Section", section),
                ("Page", block.page_no),
            ):
                if value not in (None, ""):
                    header_parts.append(f"{label}: {value}")
            contextual = "\n".join(header_parts) + "\n\n" + text
            digest = hashlib.sha256(f"{document['document_id']}:{version_no}:{ordinal}:{text}".encode()).hexdigest()
            chunk_id = f"kch-{digest[:24]}"
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
            chunks.append(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    document_id=document["document_id"],
                    version_no=version_no,
                    user_id=document.get("user_id", "default"),
                    ordinal=ordinal,
                    text=text,
                    contextual_text=contextual,
                    section_path=section,
                    page_no=block.page_no,
                    token_count=estimate_tokens(contextual),
                    qdrant_point_id=point_id,
                    metadata={
                        "parser": "native"
                        if str(document.get("filename", "")).casefold().endswith(_NATIVE_SUFFIXES)
                        else "docling"
                    },
                )
            )
            ordinal += 1
    return chunks
