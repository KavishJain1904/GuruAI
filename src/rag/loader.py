import os
import tempfile
from typing import List, Tuple
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from src.core.config import CHUNK_SIZE, CHUNK_OVERLAP

_LOADERS = {'.pdf': PyPDFLoader, '.txt': TextLoader, '.docx': Docx2txtLoader}


def load_single_document(filename: str, data: bytes, document_id: str) -> List[Document]:
    """Load, chunk, and tag one file's content with its source document metadata.

    Every resulting chunk carries `document_id` and `source` (the original
    filename, not the temp path used for parsing) so retrieved content can be
    traced back to the document it came from. PDF chunks additionally keep
    the `page` field the loader already sets (0-indexed).
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _LOADERS:
        raise ValueError(f"Unsupported file type: {ext}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        raw_docs = _LOADERS[ext](tmp_path).load()
    finally:
        os.unlink(tmp_path)

    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = splitter.split_documents(raw_docs)

    for chunk in chunks:
        chunk.metadata["document_id"] = document_id
        chunk.metadata["source"] = filename
        chunk.metadata["file_type"] = ext.lstrip(".")

    return chunks


def load_documents(file_data: List[Tuple[str, bytes, str]]) -> List[Document]:
    """Load and chunk multiple files, each tagged with its own document_id.

    file_data items are (filename, content_bytes, document_id) tuples.
    """
    all_docs: List[Document] = []
    for name, data, document_id in file_data:
        all_docs.extend(load_single_document(name, data, document_id))
    return all_docs
