"""Live end-to-end test for cross-document retrieval + source attribution.
Run with: python scratch/test_multi_doc_retrieval.py

Requires GOOGLE_API_KEY (Gemini CRAG grader) and GROQ_API_KEY (Llama answer chain)
in .env — this hits the real LLMs, no mocking, so we can see actual behavior.

Covers:
  - Two documents with clearly distinct content uploaded into one session.
  - A question that legitimately needs both documents -> both show up in sources.
  - A question that only one document can answer -> only that one shows up.
  - Prints the actual question, streamed answer, and structured sources for each case.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
import src.core.database as database
database.DB_FILE = _tmp_db.name

from fastapi.testclient import TestClient
from src.core.database import init_db
from src.rag.embedder import get_db_path
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


def make_docx_bytes(paragraphs):
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


def parse_sse(text):
    """Pull out {'chunk': ...} tokens (joined into full answer) and the final sources list."""
    answer = ""
    sources = None
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if "chunk" in obj:
            answer += obj["chunk"]
        elif "sources" in obj:
            sources = obj["sources"]
    return answer, sources


PYTHON_GENERATORS_DOC = """
Python generators are a special class of functions that simplify the creation of iterators.
A generator is defined like a normal function but uses the "yield" keyword instead of "return"
whenever it wants to send a value back to the caller. Each time yield is called, the function's
state is frozen, and execution resumes exactly where it left off the next time the generator is
asked for a value.

The single biggest advantage of Python generators is memory efficiency. Because a generator
produces values lazily, one at a time, it never needs to hold an entire sequence in memory at
once. This makes generators ideal for processing very large datasets or infinite streams, where
building a full list would exhaust available RAM. Generator expressions, written with parentheses
instead of square brackets, offer the same lazy evaluation in a compact syntax.

Generators were introduced in Python via PEP 255 and have since become a foundational tool for
writing efficient, readable iteration code without manually implementing the iterator protocol.
"""

SQL_INDEXES_DOC = """
A database index is a data structure that improves the speed of data retrieval operations on a
table, at the cost of additional writes and storage space to maintain the index structure. Most
relational databases implement indexes using B-tree structures, which keep data sorted and allow
searches, sequential access, insertions, and deletions all in logarithmic time.

The single biggest advantage of a well-chosen SQL index is query performance. Without an index,
a database must perform a full table scan, checking every row to find matches for a query's WHERE
clause. With an index on the relevant column, the database can jump almost directly to the matching
rows, turning what would be a linear-time scan into a near-logarithmic-time lookup.

Indexes are not free: every INSERT, UPDATE, or DELETE must also update every index on the affected
table, so indexes should be added deliberately on columns that are frequently filtered or joined on,
not on every column in a table.
"""

pdf_present = True
try:
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, StreamObject
except ImportError:
    pdf_present = False


def make_pdf_bytes(text_by_page):
    writer = PdfWriter()
    for text in text_by_page:
        page = writer.add_blank_page(width=400, height=600)
        # Simple content stream: one Tj per line, wrapped naively.
        lines = [text[i:i + 90] for i in range(0, len(text), 90)]
        ops = "BT /F1 10 Tf 20 580 Td 12 TL\n"
        for line in lines:
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops += f"({safe}) Tj T*\n"
        ops += "ET"
        stream = StreamObject()
        stream.set_data(ops.encode("latin-1", errors="replace"))
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


# ── Set up user + session ──
client.post("/api/auth/register", json={"username": "retrieval_tester", "password": "pw12345"})
session_id = client.post("/api/sessions").json()["session_id"]

pdf_bytes = make_pdf_bytes([PYTHON_GENERATORS_DOC])
docx_bytes = make_docx_bytes(SQL_INDEXES_DOC.split("\n\n"))

try:
    # ── Upload both documents in one session ──
    upload_resp = client.post(
        f"/api/sessions/{session_id}/upload",
        files=[
            ("files", ("python_generators.pdf", pdf_bytes, "application/pdf")),
            ("files", ("sql_indexes.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
        ],
    )
    check("upload of both documents returns 200", upload_resp.status_code == 200)
    print("\nUpload response:", json.dumps(upload_resp.json(), indent=2))

    # ── Question 1: needs BOTH documents ──
    q1 = "Compare how Python generators improve memory efficiency with how SQL indexes improve query performance."
    print(f"\n{'='*80}\nQUESTION 1 (cross-document): {q1}\n{'='*80}")
    resp1 = client.post("/api/chat", json={"session_id": session_id, "question": q1})
    check("chat request 1 returns 200", resp1.status_code == 200)
    answer1, sources1 = parse_sse(resp1.text)
    print(f"\nANSWER 1:\n{answer1}\n")
    print(f"SOURCES 1:\n{json.dumps(sources1, indent=2)}")

    filenames1 = {s.get("filename") for s in (sources1 or []) if s.get("type") == "textbook"}
    check("Q1 sources include python_generators.pdf", "python_generators.pdf" in filenames1)
    check("Q1 sources include sql_indexes.docx", "sql_indexes.docx" in filenames1)
    check("Q1 sources have structured fields (document_id/filename/page/title)",
          all({"document_id", "filename", "page", "title", "snippet"} <= s.keys() for s in (sources1 or [])))

    # ── Question 2: only ONE document is relevant ──
    q2 = "What keyword does Python use to define a generator function?"
    print(f"\n{'='*80}\nQUESTION 2 (single-document): {q2}\n{'='*80}")
    resp2 = client.post("/api/chat", json={"session_id": session_id, "question": q2})
    check("chat request 2 returns 200", resp2.status_code == 200)
    answer2, sources2 = parse_sse(resp2.text)
    print(f"\nANSWER 2:\n{answer2}\n")
    print(f"SOURCES 2:\n{json.dumps(sources2, indent=2)}")

    filenames2 = {s.get("filename") for s in (sources2 or []) if s.get("type") == "textbook"}
    check("Q2 sources include python_generators.pdf", "python_generators.pdf" in filenames2)
    check("Q2 sources do NOT include sql_indexes.docx", "sql_indexes.docx" not in filenames2)

finally:
    faiss_dir = get_db_path(session_id)
    if os.path.exists(faiss_dir):
        shutil.rmtree(faiss_dir)
    os.unlink(_tmp_db.name)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
