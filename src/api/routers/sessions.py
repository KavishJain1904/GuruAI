"""Chat session lifecycle, document upload, and the per-session knowledge base."""
import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from src.api import retriever_cache
from src.api.deps import get_current_user, verify_session_ownership
from src.rag.embedder import create_vectorstore, get_db_path, vectorstore_exists
from src.rag.loader import load_documents
from src.sessions import documents as documents_store
from src.sessions import store

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
def get_sessions(user_id: int = Depends(get_current_user)):
    """Return every session for the current user, with messages and documents."""
    return store.load_all_sessions(user_id)


@router.post("")
def create_session(user_id: int = Depends(get_current_user)):
    """Start a new, empty chat session."""
    session_id = store.create_session(user_id, "New Chat")
    return {"session_id": session_id}


@router.delete("/{session_id}")
def delete_session(session_id: str, user_id: int = Depends(get_current_user)):
    """Delete a session, its messages, and its vector store."""
    verify_session_ownership(session_id, user_id)
    store.delete_session(session_id)
    retriever_cache.invalidate(session_id)
    return {"status": "deleted"}


@router.patch("/{session_id}/title")
def update_title(
    session_id: str,
    title: str = Form(...),
    user_id: int = Depends(get_current_user)
):
    """Rename a session."""
    verify_session_ownership(session_id, user_id)
    store.update_session_title(session_id, title)
    return {"status": "updated"}


@router.get("/{session_id}/messages")
def get_messages(session_id: str, user_id: int = Depends(get_current_user)):
    """Return the full message history for a session."""
    verify_session_ownership(session_id, user_id)
    return store.get_session_messages(session_id)


@router.get("/{session_id}/db-status")
def db_status(session_id: str, user_id: int = Depends(get_current_user)):
    """Report whether a session has a built vector store."""
    verify_session_ownership(session_id, user_id)
    return {"exists": vectorstore_exists(session_id)}


@router.post("/{session_id}/upload")
async def upload_and_build(
    session_id: str,
    files: List[UploadFile] = File(...),
    user_id: int = Depends(get_current_user)
):
    """Upload one or more PDF/DOCX/TXT files into a session's shared knowledge base.

    Each file is tracked as its own document (id, type, status, storage location)
    and every resulting chunk is tagged with the document it came from (and page
    number, for paginated file types) so retrieved content stays traceable to its
    source. A file that fails to parse doesn't block the others in the same batch.
    """
    verify_session_ownership(session_id, user_id)

    all_docs = []
    results = []
    for f in files:
        content = await f.read()
        doc_id = str(uuid.uuid4())
        file_type = os.path.splitext(f.filename)[1].lower().lstrip(".")
        try:
            chunks = load_documents([(f.filename, content, doc_id)])
            if not chunks:
                raise ValueError("No readable text extracted from this file")

            documents_store.add_document(
                session_id, doc_id, f.filename, len(content), file_type,
                status="ready", storage_path=get_db_path(session_id), chunk_count=len(chunks),
            )
            all_docs.extend(chunks)
            results.append({
                "doc_id": doc_id, "filename": f.filename, "file_type": file_type,
                "status": "ready", "chunk_count": len(chunks),
            })
        except Exception as e:
            documents_store.add_document(
                session_id, doc_id, f.filename, len(content), file_type,
                status="failed", storage_path=None, chunk_count=0, error=str(e),
            )
            results.append({
                "doc_id": doc_id, "filename": f.filename, "file_type": file_type,
                "status": "failed", "error": str(e),
            })

    if not all_docs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the uploaded file(s) contained readable text. Please ensure they are not empty or scanned images without OCR."
        )

    # Merge the new chunks into the session's vectorstore (existing docs, if any, are kept)
    vectorstore = create_vectorstore(all_docs, session_id)

    # Rebuild the hybrid retriever over the FULL session docstore, not just this batch
    retriever_cache.refresh(session_id, vectorstore)

    return {"status": "database built", "doc_count": len(all_docs), "documents": results}


@router.get("/{session_id}/documents")
def get_documents(session_id: str, user_id: int = Depends(get_current_user)):
    """List the documents uploaded to a session."""
    verify_session_ownership(session_id, user_id)
    return documents_store.get_session_documents(session_id)


@router.delete("/{session_id}/knowledge")
def delete_knowledge_base(session_id: str, user_id: int = Depends(get_current_user)):
    """Wipe the FAISS vector store and document list for a session, keeping chat history intact."""
    verify_session_ownership(session_id, user_id)
    documents_store.clear_session_knowledge_base(session_id)
    retriever_cache.invalidate(session_id)
    return {"status": "knowledge base cleared"}
