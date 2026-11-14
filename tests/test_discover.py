from __future__ import annotations

import hashlib

import pytest

from oculus_pdf.discover import Document, discover_documents, sha256_file


def write_file(path, data=b"%PDF-1.4"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_sha256_file_matches_hashlib(tmp_path):
    data = b"oculus pdf" * 1000
    path = write_file(tmp_path / "data.bin", data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_sha256_file_differs_for_different_bytes(tmp_path):
    first = write_file(tmp_path / "first.bin", b"one")
    second = write_file(tmp_path / "second.bin", b"two")
    assert sha256_file(first) != sha256_file(second)


def test_missing_input_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_documents(tmp_path / "missing")


def test_input_dir_is_file(tmp_path):
    path = write_file(tmp_path / "not-a-dir")
    with pytest.raises(FileNotFoundError):
        discover_documents(path)


def test_missing_category_directory(tmp_path):
    write_file(tmp_path / "statements" / "statement.pdf")
    result = discover_documents(tmp_path)
    assert list(result) == ["invoices", "statements"]
    assert result["invoices"] == []
    assert [document.name for document in result["statements"]] == ["statement.pdf"]


def test_pdf_suffix_case_insensitive(tmp_path):
    for name in ("a.PDF", "b.Pdf", "c.pdf"):
        write_file(tmp_path / "invoices" / name)
    result = discover_documents(tmp_path)
    assert [document.name for document in result["invoices"]] == [
        "a.PDF",
        "b.Pdf",
        "c.pdf",
    ]


def test_ignores_dotfiles_non_pdfs_and_directories(tmp_path):
    invoices = tmp_path / "invoices"
    write_file(invoices / "keep.pdf")
    write_file(invoices / ".DS_Store")
    write_file(invoices / "notes.txt")
    write_file(invoices / ".hidden.pdf")
    (invoices / "x.pdf").mkdir()
    result = discover_documents(tmp_path)
    assert [document.name for document in result["invoices"]] == ["keep.pdf"]


def test_ignores_nested_pdfs(tmp_path):
    write_file(tmp_path / "invoices" / "top.pdf")
    write_file(tmp_path / "invoices" / "sub" / "nested.pdf")
    result = discover_documents(tmp_path)
    assert [document.name for document in result["invoices"]] == ["top.pdf"]


def test_sorted_case_insensitive(tmp_path):
    for name in ("b.pdf", "A.pdf", "c.pdf"):
        write_file(tmp_path / "invoices" / name)
    result = discover_documents(tmp_path)
    assert [document.name for document in result["invoices"]] == [
        "A.pdf",
        "b.pdf",
        "c.pdf",
    ]


def test_document_fields(tmp_path):
    path = write_file(tmp_path / "invoices" / "Invoice_189339.pdf")
    (document,) = discover_documents(tmp_path)["invoices"]
    assert document == Document(
        category="invoices", path=path, name="Invoice_189339.pdf"
    )


def test_custom_categories(tmp_path):
    write_file(tmp_path / "receipts" / "receipt.pdf")
    write_file(tmp_path / "invoices" / "invoice.pdf")
    result = discover_documents(tmp_path, ("receipts",))
    assert list(result) == ["receipts"]
    assert [document.name for document in result["receipts"]] == ["receipt.pdf"]
