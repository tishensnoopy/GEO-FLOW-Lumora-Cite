"""Extract text from user-supplied Citation Check documents."""

from html import unescape
from io import BytesIO
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from .fetcher import _extract_article


MAX_UPLOAD_BYTES = 5_000_000


class UnsupportedDocumentError(ValueError):
    pass


def extract_document(filename: str, raw: bytes) -> tuple[str, str]:
    if not raw:
        raise UnsupportedDocumentError("上传文件为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise UnsupportedDocumentError("上传文件不能超过 5 MB")

    suffix = Path(filename).suffix.lower()
    title = Path(filename).stem.strip() or "用户上传的文档"
    if suffix in {".txt", ".text", ".rst"}:
        return title, " ".join(_decode_text(raw).split())
    if suffix in {".html", ".htm"}:
        decoded = _decode_text(raw)
        extracted_title, text, _, _ = _extract_article(decoded, "https://uploaded.local/document")
        return extracted_title or title, text
    if suffix in {".md", ".markdown"}:
        text = _decode_text(raw)
        heading = re.search(r"^\s*#\s+(.+?)\s*$", text, re.MULTILINE)
        text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        text = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", text)
        text = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", text)
        text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"[*_~>`-]+", " ", text)
        return heading.group(1).strip() if heading else title, " ".join(text.split())
    if suffix == ".docx":
        return title, _extract_docx(raw)
    raise UnsupportedDocumentError("仅支持 DOCX、HTML、Markdown、TXT 和 RST 文件")


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_docx(raw: bytes) -> str:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise UnsupportedDocumentError("无法读取该 Word 文档，请确认文件为有效的 .docx") from exc

    root = ElementTree.fromstring(xml)
    paragraphs = []
    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        parts = [node.text or "" for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        if parts:
            paragraphs.append(unescape("".join(parts)))
    return " ".join(" ".join(paragraphs).split())
