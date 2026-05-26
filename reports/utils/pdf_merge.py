"""Merge multiple PDF byte streams into one document."""

from __future__ import annotations

from io import BytesIO


def merge_pdf_bytes(documents: list[bytes]) -> bytes:
    if not documents:
        raise ValueError("No PDF documents to merge.")
    if len(documents) == 1:
        return documents[0]

    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        import sys

        raise ImportError(
            "pypdf is required to merge report cards into one PDF. "
            f"Install it in the Django environment: {sys.executable} -m pip install 'pypdf>=4.0.0'"
        ) from exc

    writer = PdfWriter()
    for pdf_bytes in documents:
        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)

    output = BytesIO()
    writer.write(output)
    output.seek(0)
    return output.getvalue()
