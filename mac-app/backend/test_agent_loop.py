from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.agent_loop import RouteDecision, _extract_json, _rule_route, run
from agents import knowledge_agent
from agents.knowledge_agent import search_knowledge
from agents.plugins.eval import evaluate_output
from agents.plugins.snippets import _semantic_match_snippets, inject_snippets
from agents.profile import should_learn_profile


class AgentLoopTests(unittest.TestCase):
    def test_calendar_rule_resolves_tomorrow(self):
        route = _rule_route("查一下我明天的日程")
        self.assertIsNotNone(route)
        self.assertEqual(route.intent, "calendar")
        self.assertEqual(route.tool_name, "query_calendar_events")
        self.assertTrue(route.start_iso)
        self.assertTrue(route.end_iso)

    def test_knowledge_rule(self):
        route = _rule_route("根据专业文献检索 transformer 的研究结论")
        self.assertIsNotNone(route)
        self.assertEqual(route.intent, "knowledge")
        self.assertEqual(route.tool_name, "search_knowledge")

    def test_normal_dictation_has_no_rule_route(self):
        self.assertIsNone(_rule_route("帮我把这句话改得更正式"))

    def test_extract_json_from_fenced_output(self):
        parsed = _extract_json(
            '```json\n{"intent":"knowledge","confidence":0.9}\n```'
        )
        self.assertEqual(parsed["intent"], "knowledge")

    def test_local_knowledge_retrieval(self):
        previous = os.environ.get("WHISPR_KNOWLEDGE_DIR")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.environ["WHISPR_KNOWLEDGE_DIR"] = temp_dir
                Path(temp_dir, "paper.md").write_text(
                    "Transformer attention improves long-range dependency modeling. "
                    "专业术语包括注意力机制和位置编码。",
                    encoding="utf-8",
                )

                english = search_knowledge("transformer attention")
                chinese = search_knowledge("注意力机制")

                self.assertEqual(english["matches"][0]["source"], "paper.md")
                self.assertEqual(chinese["matches"][0]["source"], "paper.md")
        finally:
            if previous is None:
                os.environ.pop("WHISPR_KNOWLEDGE_DIR", None)
            else:
                os.environ["WHISPR_KNOWLEDGE_DIR"] = previous

    def test_rag_cache_reuses_unchanged_document(self):
        previous = os.environ.get("WHISPR_KNOWLEDGE_DIR")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.environ["WHISPR_KNOWLEDGE_DIR"] = temp_dir
                path = Path(temp_dir, "cached.txt")
                path.write_text("alpha retrieval context", encoding="utf-8")
                knowledge_agent._INDEX_CACHE.clear()

                with patch.object(
                    knowledge_agent,
                    "_read_document",
                    wraps=knowledge_agent._read_document,
                ) as reader:
                    search_knowledge("alpha")
                    search_knowledge("alpha")
                    self.assertEqual(reader.call_count, 1)

                    time.sleep(0.01)
                    path.write_text("beta updated context", encoding="utf-8")
                    search_knowledge("beta")
                    self.assertEqual(reader.call_count, 2)
        finally:
            knowledge_agent._INDEX_CACHE.clear()
            if previous is None:
                os.environ.pop("WHISPR_KNOWLEDGE_DIR", None)
            else:
                os.environ["WHISPR_KNOWLEDGE_DIR"] = previous

    @patch("agents.profile.load_profile")
    @patch("agents.profile.load_history")
    def test_profile_learning_uses_persistent_threshold(
        self,
        history_mock,
        profile_mock,
    ):
        history_mock.return_value = {"items": [{}] * 49}
        profile_mock.return_value = {
            "learned": {
                "last_updated": 0,
                "last_history_ts": 0,
                "learning_started_at": 0,
            }
        }
        self.assertFalse(should_learn_profile())

        history_mock.return_value = {"items": [{}] * 50}
        self.assertTrue(should_learn_profile())

    @patch("agents.profile.load_profile")
    @patch("agents.profile.load_history")
    def test_profile_learning_handles_capped_history(
        self,
        history_mock,
        profile_mock,
    ):
        history_mock.return_value = {
            "items": [{"ts": value} for value in range(1, 201)]
        }
        profile_mock.return_value = {
            "learned": {
                "last_updated": 200,
                "last_history_ts": 150,
                "learning_started_at": 0,
            }
        }
        self.assertTrue(should_learn_profile())

    @patch("agents.plugins.eval.Agent")
    def test_default_eval_uses_no_llm(self, agent_mock):
        result = evaluate_output("clean this", "Clean this.", "refine")
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["method"], "local")
        agent_mock.assert_not_called()

    @patch(
        "agents.plugins.snippets._active_snippets",
        return_value=[{
            "trigger": "zoom link",
            "expansion": "https://example.com/meeting",
            "enabled": True,
        }],
    )
    @patch(
        "agents.plugins.snippets._semantic_match_snippets",
        return_value=[0],
    )
    def test_semantic_snippet_builds_system_hint(
        self,
        semantic_mock,
        snippets_mock,
    ):
        class FakeAgent:
            current_session = {
                "snippet_raw_input": "插入我的会议链接",
                "messages": [{
                    "role": "user",
                    "content": "插入我的会议链接",
                }],
            }

        agent = FakeAgent()
        inject_snippets(agent)

        self.assertEqual(
            agent.current_session["snippet_placeholders"],
            {"«S0»": "https://example.com/meeting"},
        )
        self.assertIn(
            "Insert placeholder «S0»",
            agent.current_session["messages"][-1]["content"],
        )

    @patch("agents.plugins.snippets.Agent")
    @patch(
        "agents.plugins.snippets.get_agent_model",
        return_value="co/gemini-3-flash-preview",
    )
    def test_semantic_snippet_timeout_does_not_break_pipeline(
        self,
        model_mock,
        agent_mock,
    ):
        agent_mock.return_value.input.side_effect = TimeoutError("network timeout")

        matched = _semantic_match_snippets(
            [{"trigger": "calendar", "expansion": "calendar text"}],
            "normal dictation",
            "normal dictation",
        )

        self.assertEqual(matched, [])

    @patch("agents.agent_loop.calendar_agent.run", return_value="Team sync at 10:00.")
    @patch("agents.agent_loop.get_target_language", return_value="English")
    @patch("agents.agent_loop.classify")
    def test_loop_routes_to_calendar(
        self,
        classify_mock,
        language_mock,
        calendar_mock,
    ):
        classify_mock.return_value = RouteDecision(
            intent="calendar",
            need_tool=True,
            tool_name="query_calendar_events",
            start_iso="2026-06-09T00:00",
            end_iso="2026-06-10T00:00",
            confidence=1.0,
        )

        result = run("What is on my calendar?", "Whispr")

        self.assertEqual(result["output"], "Team sync at 10:00.")
        self.assertEqual(result["route"]["intent"], "calendar")
        calendar_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
