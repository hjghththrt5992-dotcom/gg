"""读取知识库文档：支持 md / txt / html / pdf / docx。"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

SUPPORTED = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf", ".docx"}


@dataclass
class Document:
    id: str       # 相对路径，作为文档唯一标识
    title: str
    text: str
    markdown: bool  # 是否按 Markdown 标题切分


def read_text(path: Path) -> str:
    """读取文本文件，兼容 UTF-8 和 Windows 常见的 GBK 编码。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "header"}
    BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")
        if tag in {"h1", "h2", "h3"} and not self._skip:
            self.parts.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()
        elif not self._skip:
            self.parts.append(data)


def _load_html(path: Path) -> tuple[str, str]:
    parser = _HTMLText()
    parser.feed(read_text(path))
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return parser.title, text.strip()


def _load_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("读取 PDF 需要安装 pypdf：pip install pypdf")
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _load_docx(path: Path) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    paragraphs = []
    for p in root.iter(f"{ns}p"):
        text = "".join(t.text or "" for t in p.iter(f"{ns}t"))
        style = p.find(f"{ns}pPr/{ns}pStyle")
        level = None
        if style is not None:
            m = re.search(r"(\d)$", style.get(f"{ns}val", ""))
            if m and "eading" in style.get(f"{ns}val", ""):
                level = int(m.group(1))
        if text.strip():
            paragraphs.append(("#" * level + " " + text) if level else text)
    return "\n\n".join(paragraphs)


def _first_heading(text: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def load_document(path: Path, root: Path) -> Document | None:
    suffix = path.suffix.lower()
    doc_id = path.relative_to(root).as_posix()
    title = ""
    markdown = True
    if suffix in {".md", ".markdown"}:
        text = read_text(path)
    elif suffix == ".txt":
        text = read_text(path)
        markdown = False
    elif suffix in {".html", ".htm"}:
        title, text = _load_html(path)
    elif suffix == ".pdf":
        text = _load_pdf(path)
        markdown = False
    elif suffix == ".docx":
        text = _load_docx(path)
    else:
        return None
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return None
    title = title or (_first_heading(text) if markdown else "") or path.stem
    return Document(id=doc_id, title=title, text=text, markdown=markdown)


def load_documents(docs_dir: Path) -> list[Document]:
    docs = []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED or path.name.startswith("."):
            continue
        try:
            doc = load_document(path, docs_dir)
        except Exception as e:  # 单个文件出错不影响整体
            print(f"  [跳过] {path.name}: {e}")
            continue
        if doc:
            docs.append(doc)
    return docs
