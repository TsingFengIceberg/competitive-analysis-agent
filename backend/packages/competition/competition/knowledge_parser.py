"""Safe, local document parsing for knowledge-base ingestion."""

from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
import os
import re
import threading
from pathlib import Path
from typing import Any

from competition.knowledge_types import ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "true")
_PROJECT_ROOT = Path(__file__).resolve().parents[4]

SUPPORTED_SUFFIXES = {
    ".adoc",
    ".asciidoc",
    ".csv",
    ".doc",
    ".docx",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".odp",
    ".ods",
    ".odt",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rst",
    ".text",
    ".txt",
    ".xls",
    ".xlsx",
    ".xml",
}

_TEXT_SUFFIXES = {".adoc", ".asciidoc", ".md", ".rst", ".text", ".txt"}
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def detect_media_type(path: Path, declared: str | None = None) -> str:
    if declared and declared != "application/octet-stream":
        return declared.split(";", 1)[0].strip().lower()
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _decode_text(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        from charset_normalizer import from_bytes

        match = from_bytes(raw).best()
        if match is None:
            raise ValueError("Unable to detect text encoding")
        return str(match)


def _blocks_from_markdown(markdown: str) -> list[ParsedBlock]:
    headings: list[str] = []
    blocks: list[ParsedBlock] = []
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            blocks.append(ParsedBlock(text=text, section_path=" > ".join(headings)))
        buffer.clear()

    for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            headings[:] = headings[: level - 1]
            headings.append(match.group(2).strip())
            continue
        if not line.strip() and buffer and any(item.strip() for item in buffer):
            flush()
            continue
        buffer.append(line)
    flush()
    return blocks or [ParsedBlock(text=markdown.strip())]


def _parse_html(path: Path, media_type: str) -> ParsedDocument:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_decode_text(path.read_bytes()), "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    for tag in soup.select("nav, footer, [role='navigation'], [aria-hidden='true']"):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else path.stem
    lines: list[str] = []
    for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr"]):
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        if node.name and node.name.startswith("h"):
            lines.append(f"{'#' * int(node.name[1])} {text}")
        elif node.name == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
        lines.append("")
    markdown = "\n".join(lines).strip()
    return ParsedDocument(title=title, markdown=markdown, blocks=_blocks_from_markdown(markdown), media_type=media_type)


def _parse_csv(path: Path, media_type: str) -> ParsedDocument:
    text = _decode_text(path.read_bytes())
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect=dialect))
    if not rows:
        markdown = ""
    else:
        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        header = normalized[0]
        markdown_rows = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
        markdown_rows.extend("| " + " | ".join(row) + " |" for row in normalized[1:])
        markdown = "\n".join(markdown_rows)
    return ParsedDocument(
        title=path.stem,
        markdown=markdown,
        blocks=[ParsedBlock(text=markdown, section_path=path.stem)] if markdown else [],
        media_type=media_type,
    )


def _parse_json(path: Path, media_type: str) -> ParsedDocument:
    payload = json.loads(_decode_text(path.read_bytes()))
    markdown = f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    return ParsedDocument(
        title=path.stem,
        markdown=markdown,
        blocks=[ParsedBlock(text=markdown, section_path=path.stem)],
        media_type=media_type,
    )


class DocumentParser:
    """Parse common text formats directly and rich documents through Docling."""

    def __init__(self, artifacts_path: str | Path | None = None) -> None:
        self.artifacts_path = Path(artifacts_path) if artifacts_path else _PROJECT_ROOT / ".ci-agent/models/docling"
        self._converter: Any | None = None
        self._converter_lock = threading.Lock()

    def parse(self, path: str | Path, declared_media_type: str | None = None) -> ParsedDocument:
        source = Path(path)
        suffix = source.suffix.casefold()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported document type: {suffix or 'no extension'}")
        media_type = detect_media_type(source, declared_media_type)
        if suffix in _TEXT_SUFFIXES:
            markdown = _decode_text(source.read_bytes()).strip()
            return ParsedDocument(
                title=source.stem,
                markdown=markdown,
                blocks=_blocks_from_markdown(markdown),
                media_type=media_type,
            )
        if suffix in {".htm", ".html"}:
            return _parse_html(source, media_type)
        if suffix == ".csv":
            return _parse_csv(source, media_type)
        if suffix == ".json":
            return _parse_json(source, media_type)
        return self._parse_with_docling(source, media_type)

    def _get_converter(self) -> Any:
        if self._converter is not None:
            return self._converter
        with self._converter_lock:
            if self._converter is not None:
                return self._converter
            if not self.artifacts_path.exists():
                raise RuntimeError(f"Docling artifacts not found: {self.artifacts_path}")
            from docling.datamodel.accelerator_options import AcceleratorOptions
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
            from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

            pdf_options = PdfPipelineOptions(
                artifacts_path=self.artifacts_path,
                accelerator_options=AcceleratorOptions(device="cpu", num_threads=4),
                do_ocr=True,
                ocr_options=RapidOcrOptions(backend="onnxruntime", lang=["chinese"]),
                do_table_structure=True,
                do_picture_classification=False,
                enable_remote_services=False,
                allow_external_plugins=False,
            )
            self._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
                    InputFormat.IMAGE: ImageFormatOption(pipeline_options=pdf_options),
                }
            )
        return self._converter

    def _parse_with_docling(self, path: Path, media_type: str) -> ParsedDocument:
        converter = self._get_converter()
        result = converter.convert(path)
        document = result.document
        markdown = document.export_to_markdown().strip()
        blocks: list[ParsedBlock] = []
        try:
            from docling.chunking import HierarchicalChunker

            for chunk in HierarchicalChunker().chunk(document):
                text = str(getattr(chunk, "text", "") or "").strip()
                if not text:
                    continue
                meta = getattr(chunk, "meta", None)
                headings = list(getattr(meta, "headings", None) or [])
                page_numbers: list[int] = []
                for item in list(getattr(meta, "doc_items", None) or []):
                    for provenance in list(getattr(item, "prov", None) or []):
                        page_no = getattr(provenance, "page_no", None)
                        if isinstance(page_no, int):
                            page_numbers.append(page_no)
                blocks.append(
                    ParsedBlock(
                        text=text,
                        section_path=" > ".join(str(value) for value in headings if value),
                        page_no=min(page_numbers) if page_numbers else None,
                    )
                )
        except Exception as exc:
            logger.warning("Docling block extraction degraded for %s: %s", path, exc)
        if not blocks:
            blocks = _blocks_from_markdown(markdown)
        title = str(getattr(document, "name", "") or path.stem)
        return ParsedDocument(title=title, markdown=markdown, blocks=blocks, media_type=media_type)
