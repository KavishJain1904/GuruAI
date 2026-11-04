"""A study suggestion must be backed by both mastery and the curriculum graph."""
import unittest
from unittest.mock import patch
from langchain_core.runnables import RunnableLambda

from src.personalization import topic_graph_seed
from src.rag import learning_advisor
from src.rag.learning_advisor import _validate_recommendation


PROFILE = """  Subject: Operating Systems
    - Weak (30%): CPU Scheduling
    - Strong (85%): Process Management
"""
GRAPH = {
    "nodes": ["Processes", "Scheduling Algorithms", "Deadlocks"],
    "edges": [
        {"from": "Processes", "to": "Scheduling Algorithms", "relation": "prerequisite_of"},
        {"from": "Scheduling Algorithms", "to": "Deadlocks", "relation": "prerequisite_of"},
    ],
}


class PrerequisiteSuggestionTests(unittest.TestCase):
    def setUp(self):
        self.graph_patch = patch("src.rag.learning_advisor.topic_graph.get_subject_graph", return_value=GRAPH)
        self.graph_patch.start()
        self.addCleanup(self.graph_patch.stop)

    def test_weak_profile_alias_on_real_path_is_suggested(self):
        candidate = {
            "subject": "Operating Systems",
            "target_topic": "Deadlocks",
            "graph_prerequisite": "Scheduling Algorithms",
            "profile_prerequisite": "CPU Scheduling",
        }
        self.assertEqual(_validate_recommendation(candidate, PROFILE), {
            "subject": "Operating Systems", "topic": "Cpu Scheduling",
            "score": 30, "for_topic": "Deadlocks",
        })

    def test_strong_topic_is_not_suggested(self):
        candidate = {
            "subject": "Operating Systems",
            "target_topic": "Scheduling Algorithms",
            "graph_prerequisite": "Processes",
            "profile_prerequisite": "Process Management",
        }
        self.assertIsNone(_validate_recommendation(candidate, PROFILE))

    def test_unrelated_graph_node_is_not_suggested(self):
        candidate = {
            "subject": "Operating Systems",
            "target_topic": "Processes",
            "graph_prerequisite": "Scheduling Algorithms",
            "profile_prerequisite": "CPU Scheduling",
        }
        self.assertIsNone(_validate_recommendation(candidate, PROFILE))

    def test_existing_os_graph_gets_missing_kernel_prerequisite(self):
        existing_graph = {
            "nodes": ["Kernel Design", "Scheduling Algorithms", "Process Management"],
            "edges": [
                {"from": "Process Management", "to": "Kernel Design", "relation": "prerequisite_of"},
                {"from": "Process Management", "to": "Scheduling Algorithms", "relation": "prerequisite_of"},
            ],
        }
        with (patch("src.personalization.topic_graph_seed.topic_graph.get_subject_graph",
                    side_effect=lambda subject: existing_graph if subject == "Operating System"
                    else {"nodes": [], "edges": []}),
              patch("src.personalization.topic_graph_seed.topic_graph.add_edge") as add_edge):
            topic_graph_seed.apply_curated_graph_corrections()
        add_edge.assert_called_once_with(
            "Operating System", "Scheduling Algorithms", "Kernel Design", source="seed"
        )

    def test_exact_question_match_surfaces_weak_prerequisite_without_advisor_json(self):
        graph = {
            "nodes": ["Kernel Design", "Scheduling Algorithms"],
            "edges": [{"from": "Scheduling Algorithms", "to": "Kernel Design",
                       "relation": "prerequisite_of"}],
        }
        profile = "  Subject: Operating Systems\n    - Weak (30%): Scheduling Algorithms"
        with (patch.object(learning_advisor.topic_graph, "get_subject_graph", return_value=graph),
              patch.object(learning_advisor.topic_graph, "format_graph_context", return_value="graph"),
              patch.object(learning_advisor, "_log_advisor_prompt", side_effect=lambda prompt: prompt),
              patch.object(learning_advisor, "_advisor_llm", RunnableLambda(
                  lambda _: '{"guidance":"Normal explanation","recommendation":null}'))):
            guidance, suggestion = learning_advisor.build_learning_guidance_with_recommendation(
                1, "Explain kernel design", profile_summary=profile
            )
        self.assertEqual(suggestion["topic"], "Scheduling Algorithms")
        self.assertEqual(suggestion["for_topic"], "Kernel Design")
        self.assertIn("weak in Scheduling Algorithms", guidance)


if __name__ == "__main__":
    unittest.main()
