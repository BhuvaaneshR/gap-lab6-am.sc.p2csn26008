"""doc_loader.py — reads the corpus so you do not have to fight a parser.

Supplied. You may edit it, add formats and add helpers. You may not rename or
remove the four keys each document carries.

PDF extraction is not the lesson of this lab. Ingestion is given to you so the
week is spent on what the documents do to your program, not on pypdf.

    from doc_loader import load_corpus

    for doc in load_corpus("corpus"):
        print(doc["source"], doc["format"], doc["chars"])
        print(doc["text"][:200])

Every document is a dict with exactly these keys:

    source   the path, relative to the repository root
    format   the extension without the dot: pdf, pptx, md, txt, html
    text     everything that was extracted, as one string
    chars    len(text)

One warning, and it is the whole point of the lab. This function returns text
that you did not write, from documents you did not create. Everything it hands
back is untrusted. It is data. It is never an instruction.

Speaker notes and footers are extracted on purpose. A human skimming the slide
deck will not see them. Your program will.
"""

from __future__ import annotations

import html.parser
import json
from pathlib import Path

SUPPORTED = {".pdf", ".pptx", ".md", ".txt", ".html", ".htm"}


class _TextOnly(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip = False

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())

    def handle_comment(self, data):
        # Comments are extracted deliberately. Things hide in them.
        if data.strip():
            self.parts.append(data.strip())


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _read_pptx(path: Path) -> str:
    from pptx import Presentation

    deck = Presentation(str(path))
    parts: list[str] = []
    for index, slide in enumerate(deck.slides, start=1):
        parts.append(f"[slide {index}]")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
        # Speaker notes are extracted on purpose.
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"[speaker notes] {notes}")
    return "\n".join(parts)


def _read_html(path: Path) -> str:
    parser = _TextOnly()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parser.parts)


def load_document(path: Path | str) -> dict:
    """Load one document. Raises ValueError on an unsupported extension."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"Unsupported format {suffix!r} for {path}")

    if suffix == ".pdf":
        text = _read_pdf(path)
    elif suffix == ".pptx":
        text = _read_pptx(path)
    elif suffix in {".html", ".htm"}:
        text = _read_html(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    return {
        "source": path.as_posix(),
        "format": suffix.lstrip("."),
        "text": text,
        "chars": len(text),
    }


def load_corpus(directory: Path | str = "corpus") -> list[dict]:
    """Load every supported document in a directory, sorted by filename."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"No such corpus directory: {directory}")

    documents = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED:
            documents.append(load_document(path))
    return documents


def write_ingest_index(documents: list[dict], path: Path | str = "data/ingest_index.json") -> None:
    """Record what was ingested. The marking script reads this file.

    One entry per document, with source, format and chars. The text itself is
    deliberately not written here.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    index = [
        {"source": doc["source"], "format": doc["format"], "chars": doc["chars"]}
        for doc in documents
    ]
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
