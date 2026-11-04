"""Streaming RAG chat endpoint."""
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from src.api import retriever_cache
from src.api.deps import get_current_user, verify_session_ownership
from src.api.schemas import ChatRequest
from src.personalization import mastery, user_memory
from src.rag.chain import build_rag_chain
from src.rag.crag import build_crag_context
from src.rag.learning_advisor import build_learning_guidance_with_recommendation
from src.sessions import store

router = APIRouter(prefix="/api", tags=["chat"])

# Only the last few turns are replayed to the LLM, to keep prompt size bounded.
_HISTORY_TURNS = 4


def _generation_error_message(error: Exception) -> str:
    """Report useful provider failures without exposing credentials or request data."""
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    name = type(error).__name__.lower()
    if status in (401, 403) or "authentication" in name or "permissiondenied" in name:
        return "AI service authentication failed. Check the GROQ_API_KEY used by the running server."
    if status == 429 or "ratelimit" in name or "resourceexhausted" in name:
        return "The AI service rate limit or quota was reached. Please try again later."
    if "connection" in name or "timeout" in name:
        return "Could not reach the AI service. Check the server's network connection."
    return "The AI service failed while generating an answer. Check the server logs."


@router.post("/chat")
def chat(req: ChatRequest, user_id: int = Depends(get_current_user)):
    """Answer with session documents when available, otherwise general knowledge.

    Emits `{"chunk": ...}` frames as the model produces tokens, then a single
    `{"sources": [...]}` frame, then `[DONE]`. The full answer and its sources
    are persisted once the stream completes.
    """
    verify_session_ownership(req.session_id, user_id)
    retriever = retriever_cache.get(req.session_id)
    general_knowledge_mode = retriever is None

    profile_summary = mastery.build_profile_summary(user_id)
    print(profile_summary)
    memory_context = user_memory.get_memory_as_system_context(user_id)
    # Dedicated pre-processing call: reasons over the profile + prerequisite
    # graph together before the answer-generation call even starts. Runs
    # before streaming begins, so it adds its own latency to every request;
    # returns "" (skip/fallback) if there's no profile yet or the call fails.
    learning_guidance, recommendation = build_learning_guidance_with_recommendation(
        user_id, req.question, profile_summary=profile_summary
    )
    chain = build_rag_chain(
        retriever,
        knowledge_profile_summary=profile_summary,
        user_memory_context=memory_context,
        learning_guidance=learning_guidance,
        general_knowledge_mode=general_knowledge_mode,
    )

    history_raw = store.get_session_messages(req.session_id)
    # Filter out quiz messages from LLM history
    text_history = [m for m in history_raw if m["role"] in ("user", "assistant")]

    # Token optimization: limit history to the last 2 QA pairs
    if len(text_history) > _HISTORY_TURNS:
        text_history = text_history[-_HISTORY_TURNS:]

    if not text_history:
        title = req.question[:25] + "..." if len(req.question) > 25 else req.question
        store.update_session_title(req.session_id, title)

    store.add_message(req.session_id, "user", req.question)

    formatted_history = []
    for h in text_history:
        if h["role"] == "user":
            formatted_history.append(HumanMessage(content=h["content"]))
        else:
            formatted_history.append(AIMessage(content=h["content"]))

    # A document-free chat should not retrieve, grade, or web-search. The same
    # mastery/prerequisite guidance above still shapes its general-knowledge answer.
    if general_knowledge_mode:
        context_text, source_label, sources_metadata = "", "[General Knowledge]", []
    else:
        context_text, source_label, sources_metadata = build_crag_context(retriever, req.question)
    print(f"[Chat] Source label: {source_label} | Sources count: {len(sources_metadata)}")

    def generate():
        full_response = ""
        completed = False
        try:
            for chunk in chain.stream({
                "question": req.question,
                "context": context_text,
                "chat_history": formatted_history,
            }):
                full_response += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            # Emit sources metadata before [DONE] so the UI can attach the drawer
            yield f"data: {json.dumps({'sources': sources_metadata})}\n\n"
            if recommendation:
                yield f"data: {json.dumps({'recommendation': recommendation})}\n\n"
            completed = True
            yield "data: [DONE]\n\n"
        except Exception as error:
            print(f"[Chat] Generation failed: {type(error).__name__} "
                  f"(status={getattr(error, 'status_code', 'unknown')})")
            yield f"data: {json.dumps({'error': _generation_error_message(error)})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if full_response:
                store.add_message(req.session_id, "assistant", full_response,
                                  sources=sources_metadata,
                                  recommendation=recommendation if completed else None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
