"""把文档切成适合检索的小块。

规则：按 Markdown 标题分节 → 节内按段落和句子装箱，每块不超过 CHUNK_SIZE 字；
同一节内相邻块重叠 CHUNK_OVERLAP 字；很短的小节会和后面的小节合并，避免碎块。
每块都记录"文档标题 + 小节路径"，检索和生成时一起使用，防止断章取义。
"""
from __future__ import annotations

import re

from config import CHUNK_OVERLAP, CHUNK_SIZE
from kb_builder.loaders import Document

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SENTENCE_END = re.compile(r"(?<=[。！？；!?;\n])")

Unit = tuple  # (section, text, is_heading)


def _split_long(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def _units(doc: Document, size: int) -> list[Unit]:
    """把文档拆成最小单元（句子或标题）序列，每个单元带所属小节路径。"""
    units: list[Unit] = []
    stack: list[tuple[int, str]] = []
    para: list[str] = []
    in_code = False

    def section() -> str:
        return " > ".join(t for _, t in stack)

    def end_paragraph():
        text = "\n".join(para).strip()
        para.clear()
        if not text:
            return
        sentences = [s for s in SENTENCE_END.split(text) if s]
        for i, s in enumerate(sentences):
            if i == len(sentences) - 1 and not s.endswith("\n"):
                s += "\n"
            for piece in _split_long(s, size):
                units.append((section(), piece, False))

    for line in doc.text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        m = HEADING.match(line) if doc.markdown and not in_code else None
        if m:
            end_paragraph()
            level, title = len(m.group(1)), m.group(2).strip()
            if level == 1 and title == doc.title and not stack:
                continue  # 文档大标题已经作为 title 记录
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            units.append((section(), f"【{title}】\n", True))
        elif line.strip():
            para.append(line.rstrip())
        else:
            end_paragraph()
    end_paragraph()
    return units


def chunk_document(doc: Document, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    min_size = size // 3
    chunks: list[dict] = []
    buf: list[Unit] = []

    def emit():
        # 块首的标题已经体现在 section 里，不再重复放进正文
        body = buf[1:] if buf and buf[0][2] else buf
        text = "".join(u[1] for u in body).strip()
        if text:
            chunks.append({
                "id": f"{doc.id}#{len(chunks)}",
                "doc": doc.id,
                "title": doc.title,
                "section": buf[0][0],
                "text": text,
            })

    for unit in _units(doc, size):
        sec, text, is_heading = unit
        length = sum(len(u[1]) for u in buf)
        if is_heading:
            if length >= min_size:
                emit()
                buf = []
            buf.append(unit)
            continue
        if buf and length + len(text) > size:
            emit()
            tail: list[Unit] = []
            n = 0
            for u in reversed(buf):  # 同一小节内保留末尾几句作为重叠
                if u[2] or u[0] != sec or n + len(u[1]) > overlap:
                    break
                tail.insert(0, u)
                n += len(u[1])
            buf = tail
        buf.append(unit)
    emit()
    return chunks


def chunk_header(chunk: dict) -> str:
    """资料的标题行，例如：《检索增强生成》 > 混合检索"""
    header = f"《{chunk['title']}》"
    if chunk.get("section"):
        header += f" > {chunk['section']}"
    return header


def embed_text(chunk: dict) -> str:
    return f"{chunk_header(chunk)}\n{chunk['text']}"
