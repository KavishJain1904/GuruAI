"""Persistent per-user memory: stored preferences and the memory chat bot."""
from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.api.schemas import MemoryMessageRequest
from src.personalization import user_memory

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("")
def get_memory(user_id: int = Depends(get_current_user)):
    """Return all stored memory items."""
    return {"items": user_memory.load_memory(user_id)}


@router.post("")
def add_memory(req: MemoryMessageRequest, user_id: int = Depends(get_current_user)):
    """Accept a free-form message from the user, extract preferences via LLM,
    store them, and return the full updated memory list.
    """
    extracted = user_memory.extract_preferences_from_message(user_id, req.message)
    updated = user_memory.add_memory_items(user_id, extracted)
    return {"extracted": extracted, "items": updated}


@router.delete("")
def clear_memory(user_id: int = Depends(get_current_user)):
    """Clear all memory items."""
    user_memory.clear_all_memory(user_id)
    return {"items": []}


@router.get("/chat")
def get_memory_chat(user_id: int = Depends(get_current_user)):
    """Return the persistent memory chat history."""
    return {"history": user_memory.get_chat_history(user_id)}


@router.post("/chat")
def memory_chat_message(req: MemoryMessageRequest, user_id: int = Depends(get_current_user)):
    """Send a message to the memory chat bot.

    It responds conversationally and silently extracts + stores preferences.
    """
    reply, extracted = user_memory.memory_chat(user_id, req.message)
    return {
        "reply": reply,
        "extracted": extracted,
        "items": user_memory.load_memory(user_id),
    }


# Declared after /chat so the literal path wins over this integer-typed one.
@router.delete("/{index}")
def delete_memory(index: int, user_id: int = Depends(get_current_user)):
    """Delete a memory item by its index."""
    return {"items": user_memory.delete_memory_item(user_id, index)}
