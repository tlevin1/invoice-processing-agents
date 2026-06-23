"""Tests for tools/file_reader.py — no API calls needed."""
import pytest
from tools.file_reader import read_invoice

DIR = "data/invoices"


@pytest.mark.parametrize("fname,expected_fmt,must_contain", [
    ("invoice_1001.txt",  "txt",  "INV-1001"),
    ("invoice_1004.json", "json", "INV-1004"),
    ("invoice_1006.csv",  "csv",  "INV-1006"),
    ("invoice_1014.xml",  "xml",  "INV-1014"),
    ("invoice_1011.pdf",  "pdf",  "INV-1011"),
])
def test_read_format(fname, expected_fmt, must_contain):
    content, fmt = read_invoice(f"{DIR}/{fname}")
    assert fmt == expected_fmt
    assert len(content) > 20
    assert must_contain in content


def test_unsupported_extension(tmp_path):
    f = tmp_path / "invoice.xlsx"
    f.write_text("data")
    with pytest.raises(ValueError, match="Unsupported"):
        read_invoice(str(f))


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        read_invoice(f"{DIR}/does_not_exist.txt")


def test_pdf_extracts_text():
    content, _ = read_invoice(f"{DIR}/invoice_1012.pdf")
    assert "WidgetB" in content or "Widget" in content


def test_xml_preserves_tags():
    content, _ = read_invoice(f"{DIR}/invoice_1014.xml")
    assert "<invoice>" in content
    assert "<line_items>" in content
