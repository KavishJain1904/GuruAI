"""Manual test script for Multi-Document Session Intelligence.
Run with: python scratch/test_multi_doc_upload.py

Covers:
  - Uploading 2+ files (PDF + DOCX) to a session in a single request.
  - Each file tracked as its own document row (doc_id, file_type, status, storage_path, chunk_count).
  - Every retrieved chunk in the session's vectorstore carries document_id/source/file_type,
    and PDF chunks carry the correct (0-indexed) page number.
  - A second upload batch merges into the session instead of wiping out earlier documents.
  - An unsupported file type in a batch fails on its own without blocking the other files.
"""
import io
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Point the app at a throwaway SQLite file before importing anything that opens it.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
import src.core.database as database
database.DB_FILE = _tmp_db.name

from fastapi.testclient import TestClient
from src.core.database import init_db
from src.rag.embedder import load_existing_vectorstore, get_db_path
import server

init_db()
client = TestClient(server.app)

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"PASS: {label}")
        passed += 1
    else:
        print(f"FAIL: {label}")
        failed += 1


# ── Fixture builders (no extra deps: hand-rolled minimal PDF/DOCX) ──

def make_pdf_bytes(pages_text):
    """A minimal multi-page PDF built with pypdf, readable by PyPDFLoader."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, StreamObject

    writer = PdfWriter()
    for text in pages_text:
        page = writer.add_blank_page(width=200, height=200)
        content = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode("latin-1")
        stream = StreamObject()
        stream.set_data(content)
        stream_ref = writer._add_object(stream)

        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        font_ref = writer._add_object(font)

        resources = DictionaryObject()
        font_dict = DictionaryObject()
        font_dict[NameObject("/F1")] = font_ref
        resources[NameObject("/Font")] = font_dict

        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = stream_ref

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def make_docx_bytes(paragraphs):
    """A minimal .docx (zip + bare document.xml), readable by Docx2txtLoader."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>''')
        z.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>''')
        body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
        z.writestr("word/document.xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>{body}</w:body>
</w:document>''')
    return buf.getvalue()


# ── Set up a real user + session through the actual API ──

register_resp = client.post("/api/auth/register", json={"username": "multidoc_tester", "password": "pw12345"})
check("register succeeds", register_resp.status_code == 200)

session_resp = client.post("/api/sessions")
check("session creation succeeds", session_resp.status_code == 200)
session_id = session_resp.json()["session_id"]

pdf_bytes = make_pdf_bytes(["Neural networks learn via backpropagation.", "Gradient descent minimizes the loss function."])
docx_bytes = make_docx_bytes(["Databases use B-trees for indexing.", "Normalization reduces data redundancy."])

try:
    # ── 1. Upload 2 files in a single batch ──
    upload_resp = client.post(
        f"/api/sessions/{session_id}/upload",
        files=[
            ("files", ("ml_notes.pdf", pdf_bytes, "application/pdf")),
            ("files", ("db_notes.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
        ],
    )
    check("upload of 2 files returns 200", upload_resp.status_code == 200)
    upload_json = upload_resp.json()
    check("response reports doc_count > 0", upload_json.get("doc_count", 0) > 0)

    results = {r["filename"]: r for r in upload_json.get("documents", [])}
    check("response lists both filenames", set(results.keys()) == {"ml_notes.pdf", "db_notes.docx"})
    check("both files reported as ready", all(r["status"] == "ready" for r in results.values()))
    check(
        "each file got a distinct doc_id",
        results["ml_notes.pdf"]["doc_id"] != results["db_notes.docx"]["doc_id"]
    )

    # ── 2. Documents are tracked separately in SQLite (via the real endpoint) ──
    docs_resp = client.get(f"/api/sessions/{session_id}/documents")
    check("documents endpoint returns 200", docs_resp.status_code == 200)
    docs = docs_resp.json()
    check("2 documents tracked after first batch", len(docs) == 2)

    by_name = {d["name"]: d for d in docs}
    check("ml_notes.pdf tracked with correct file_type", by_name.get("ml_notes.pdf", {}).get("file_type") == "pdf")
    check("db_notes.docx tracked with correct file_type", by_name.get("db_notes.docx", {}).get("file_type") == "docx")
    check("ml_notes.pdf status is ready", by_name.get("ml_notes.pdf", {}).get("status") == "ready")
    check("db_notes.docx status is ready", by_name.get("db_notes.docx", {}).get("status") == "ready")
    check("ml_notes.pdf has a doc_id", bool(by_name.get("ml_notes.pdf", {}).get("doc_id")))
    check(
        "ml_notes.pdf doc_id matches upload response",
        by_name["ml_notes.pdf"]["doc_id"] == results["ml_notes.pdf"]["doc_id"]
    )
    check("ml_notes.pdf storage_path points at the session's vectorstore dir",
          by_name["ml_notes.pdf"]["storage_path"] == get_db_path(session_id))
    check("ml_notes.pdf chunk_count > 0", by_name.get("ml_notes.pdf", {}).get("chunk_count", 0) > 0)
    check(
        "chunk_count sums match reported doc_count",
        by_name["ml_notes.pdf"]["chunk_count"] + by_name["db_notes.docx"]["chunk_count"] == upload_json["doc_count"]
    )

    # ── 3. Every chunk in the vectorstore carries correct source metadata ──
    db = load_existing_vectorstore(session_id)
    check("vectorstore exists after upload", db is not None)
    all_chunks = list(db.docstore._dict.values())

    pdf_doc_id = results["ml_notes.pdf"]["doc_id"]
    docx_doc_id = results["db_notes.docx"]["doc_id"]

    pdf_chunks = [c for c in all_chunks if c.metadata.get("document_id") == pdf_doc_id]
    docx_chunks = [c for c in all_chunks if c.metadata.get("document_id") == docx_doc_id]

    check("some chunks tagged with the PDF's document_id", len(pdf_chunks) > 0)
    check("some chunks tagged with the DOCX's document_id", len(docx_chunks) > 0)
    check(
        "PDF chunks carry the real filename (not a tmp path) as source",
        all(c.metadata.get("source") == "ml_notes.pdf" for c in pdf_chunks)
    )
    check(
        "DOCX chunks carry the real filename (not a tmp path) as source",
        all(c.metadata.get("source") == "db_notes.docx" for c in docx_chunks)
    )
    check("PDF chunks tagged with file_type=pdf", all(c.metadata.get("file_type") == "pdf" for c in pdf_chunks))
    check("DOCX chunks tagged with file_type=docx", all(c.metadata.get("file_type") == "docx" for c in docx_chunks))
    check(
        "PDF chunks carry a page number (0-indexed)",
        all(c.metadata.get("page") is not None for c in pdf_chunks)
    )
    pdf_pages = sorted({c.metadata.get("page") for c in pdf_chunks})
    check("PDF pages observed are exactly {0, 1} (both pages present)", pdf_pages == [0, 1])
    check(
        "DOCX chunks have no page number (docx has no pagination)",
        all(c.metadata.get("page") is None for c in docx_chunks)
    )
    check("no chunk from either file bleeds into the other's document_id", not (set(c.metadata.get("document_id") for c in pdf_chunks) & set(c.metadata.get("document_id") for c in docx_chunks)))

    # ── 4. A second upload batch merges instead of overwriting ──
    docx2_bytes = make_docx_bytes(["Operating systems schedule processes via round robin."])
    upload2_resp = client.post(
        f"/api/sessions/{session_id}/upload",
        files=[("files", ("os_notes.docx", docx2_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
    )
    check("second upload batch returns 200", upload2_resp.status_code == 200)

    docs_after_2 = client.get(f"/api/sessions/{session_id}/documents").json()
    check("3 documents tracked after second batch (accumulated, not replaced)", len(docs_after_2) == 3)

    db_after_2 = load_existing_vectorstore(session_id)
    all_chunks_after_2 = list(db_after_2.docstore._dict.values())
    doc_ids_after_2 = {c.metadata.get("document_id") for c in all_chunks_after_2}
    check(
        "vectorstore still contains chunks from the FIRST batch's documents after a second upload",
        pdf_doc_id in doc_ids_after_2 and docx_doc_id in doc_ids_after_2
    )
    check(
        "vectorstore also contains chunks from the new document",
        any(c.metadata.get("source") == "os_notes.docx" for c in all_chunks_after_2)
    )

    # ── 5. An unsupported file type fails on its own without blocking the batch ──
    upload3_resp = client.post(
        f"/api/sessions/{session_id}/upload",
        files=[
            ("files", ("notes.xyz", b"unsupported content", "application/octet-stream")),
            ("files", ("more_notes.docx", make_docx_bytes(["Compilers perform lexical analysis first."]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
        ],
    )
    check("mixed-validity batch still returns 200 (partial success)", upload3_resp.status_code == 200)
    results3 = {r["filename"]: r for r in upload3_resp.json().get("documents", [])}
    check("unsupported file reported as failed", results3.get("notes.xyz", {}).get("status") == "failed")
    check("valid file in the same batch still reported as ready", results3.get("more_notes.docx", {}).get("status") == "ready")

    docs_final = client.get(f"/api/sessions/{session_id}/documents").json()
    by_name_final = {d["name"]: d for d in docs_final}
    check("failed document tracked with status=failed", by_name_final.get("notes.xyz", {}).get("status") == "failed")
    check("failed document has an error message recorded", bool(by_name_final.get("notes.xyz", {}).get("error")))
    check("failed document has zero chunk_count", by_name_final.get("notes.xyz", {}).get("chunk_count") == 0)

finally:
    # Clean up the FAISS index directory this test created on disk.
    faiss_dir = get_db_path(session_id)
    if os.path.exists(faiss_dir):
        shutil.rmtree(faiss_dir)
    os.unlink(_tmp_db.name)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
