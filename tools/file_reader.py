"""Multi-format invoice file reader. Returns raw text content for LLM extraction."""
import json
from pathlib import Path
from typing import Tuple


def read_invoice(file_path: str) -> Tuple[str, str]:
    """
    Read an invoice file and return (content_str, format_name).
    Content is always a string — the LLM handles parsing from raw text.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Invoice file not found: {file_path}")

    suffix = path.suffix.lower()
    dispatch = {
        ".txt":  _read_txt,
        ".json": _read_json,
        ".csv":  _read_csv,
        ".pdf":  _read_pdf,
        ".xml":  _read_xml,
    }
    if suffix not in dispatch:
        raise ValueError(f"Unsupported file format '{suffix}'. Supported: {list(dispatch)}")

    return dispatch[suffix](path), suffix.lstrip(".")


def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(data, indent=2)


def _read_csv(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber is required for PDF support.\n"
            "Install it with:  pip install pdfplumber"
        )
    with pdfplumber.open(str(path)) as pdf:
        pages = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    if not pages:
        raise ValueError(f"Could not extract any text from PDF: {path}")
    return "\n\n".join(pages)


def _read_xml(path: Path) -> str:
    return path.read_text(encoding="utf-8")
