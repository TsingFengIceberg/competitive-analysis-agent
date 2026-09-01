from __future__ import annotations

import zipfile

from competition.knowledge_parser import DocumentParser


def test_docx_fallback_extracts_text_without_docling(tmp_path):
    path = tmp_path / "brief.docx"
    document_xml = b'''<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Cursor pricing</w:t></w:r></w:p></w:body></w:document>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    parsed = DocumentParser().parse(path)
    assert "Cursor pricing" in parsed.markdown


def test_xlsx_fallback_extracts_shared_strings(tmp_path):
    path = tmp_path / "facts.xlsx"
    shared = b'''<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Codex</t></si></sst>'''
    sheet = b'''<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c t="s"><v>0</v></c></row></sheetData></worksheet>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    parsed = DocumentParser().parse(path)
    assert "Codex" in parsed.markdown
