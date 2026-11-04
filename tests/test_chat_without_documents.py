"""Document-free chat keeps personalization and skips the retrieval pipeline."""
import json
import unittest
from unittest.mock import Mock, patch
from langchain_core.runnables import RunnableLambda

from src.api.routers import chat as chat_router
from src.api.schemas import ChatRequest
from src.rag import chain as tutor_chain


class ChatWithoutDocumentsTests(unittest.TestCase):
    def test_streaming_provider_failure_is_sent_to_browser(self):
        class AuthenticationFailure(Exception):
            status_code = 401

        chain = Mock()
        chain.stream.side_effect = AuthenticationFailure("invalid key")
        request = ChatRequest(session_id="test-session", question="Explain scheduling")
        with (patch.object(chat_router, "verify_session_ownership"),
              patch.object(chat_router.retriever_cache, "get", return_value=None),
              patch.object(chat_router.mastery, "build_profile_summary", return_value=""),
              patch.object(chat_router.user_memory, "get_memory_as_system_context", return_value=""),
              patch.object(chat_router, "build_learning_guidance_with_recommendation",
                           return_value=("", None)),
              patch.object(chat_router, "build_rag_chain", return_value=chain),
              patch.object(chat_router.store, "get_session_messages", return_value=[]),
              patch.object(chat_router.store, "update_session_title"),
              patch.object(chat_router.store, "add_message"),
              patch.object(chat_router, "StreamingResponse", side_effect=lambda stream, **_: stream)):
            frames = list(chat_router.chat(request, user_id=1))

        error_frame = next(frame for frame in frames if '"error"' in frame)
        message = json.loads(error_frame[6:].strip())["error"]
        self.assertIn("GROQ_API_KEY", message)
        self.assertNotIn("invalid key", message)

    def test_general_knowledge_prompt_has_no_textbook_dependency(self):
        prompts = []
        with (patch.object(tutor_chain, "llm_default", RunnableLambda(lambda _: "Answer")),
              patch.object(tutor_chain, "_log_final_prompt", side_effect=lambda prompt: (
                  prompts.append(prompt.to_string()) or prompt))):
            chain = tutor_chain.build_rag_chain(
                None, knowledge_profile_summary="Weak (30%): Cpu Scheduling",
                learning_guidance="Explain scheduling slowly because its prerequisite is weak.",
                general_knowledge_mode=True,
            )
            self.assertEqual(chain.invoke({
                "question": "Explain scheduling", "context": "", "chat_history": [],
            }), "Answer")

        prompt = prompts[0]
        self.assertIn("Answer from your general knowledge", prompt)
        self.assertIn("Explain scheduling slowly", prompt)
        self.assertNotIn("Textbook Facts", prompt)

    def test_general_knowledge_chat_keeps_guidance_and_suggestion(self):
        suggestion = {"subject": "Operating Systems", "topic": "Cpu Scheduling",
                      "score": 30, "for_topic": "Scheduling Algorithms"}
        chain = Mock()
        chain.stream.return_value = iter(["Scheduling ", "uses queues."])
        request = ChatRequest(session_id="test-session", question="Explain scheduling")

        with (patch.object(chat_router, "verify_session_ownership"),
              patch.object(chat_router.retriever_cache, "get", return_value=None),
              patch.object(chat_router.mastery, "build_profile_summary", return_value="profile"),
              patch.object(chat_router.user_memory, "get_memory_as_system_context", return_value=""),
              patch.object(chat_router, "build_learning_guidance_with_recommendation",
                           return_value=("Explain slowly", suggestion)),
              patch.object(chat_router, "build_rag_chain", return_value=chain) as build_chain,
              patch.object(chat_router, "build_crag_context") as crag,
              patch.object(chat_router.store, "get_session_messages", return_value=[]),
              patch.object(chat_router.store, "update_session_title"),
              patch.object(chat_router.store, "add_message") as save_message,
              patch.object(chat_router, "StreamingResponse", side_effect=lambda stream, **_: stream)):
            frames = list(chat_router.chat(request, user_id=1))

        build_chain.assert_called_once_with(
            None, knowledge_profile_summary="profile", user_memory_context="",
            learning_guidance="Explain slowly", general_knowledge_mode=True,
        )
        crag.assert_not_called()
        self.assertEqual(chain.stream.call_args.args[0]["context"], "")
        self.assertIn("Scheduling uses queues.", "".join(json.loads(frame[6:].strip())["chunk"]
                                                  for frame in frames if '"chunk"' in frame))
        self.assertTrue(any('"recommendation"' in frame for frame in frames))
        save_message.assert_any_call(
            "test-session", "assistant", "Scheduling uses queues.",
            sources=[], recommendation=suggestion,
        )


if __name__ == "__main__":
    unittest.main()
