"""Idempotency keys are order-independent and change with the session, the tool, or the arguments."""

import unittest

from pydantic import BaseModel

from fieldsight.harness.idempotency import canonicalize, idempotency_key


class Query(BaseModel):
    query: str
    doc_type: str | None = None


class IdempotencyTests(unittest.TestCase):
    def test_key_order_does_not_matter_at_any_depth(self) -> None:
        first = {"rule_id": "R2", "inputs": {"event_type": "fatality", "hours": 23.5}}
        second = {"inputs": {"hours": 23.5, "event_type": "fatality"}, "rule_id": "R2"}
        self.assertEqual(canonicalize(first), canonicalize(second))
        self.assertEqual(idempotency_key("s1", "evaluate_rule", first), idempotency_key("s1", "evaluate_rule", second))

    def test_set_order_does_not_matter_but_list_order_does(self) -> None:
        self.assertEqual(canonicalize({"ids": {"b", "a"}}), canonicalize({"ids": {"a", "b"}}))
        self.assertNotEqual(canonicalize({"ids": ["b", "a"]}), canonicalize({"ids": ["a", "b"]}))

    def test_a_model_and_its_dict_give_the_same_key(self) -> None:
        model = Query(query="1904.39", doc_type="regulation")
        self.assertEqual(idempotency_key("s1", "search_knowledge_base", model),
                         idempotency_key("s1", "search_knowledge_base", {"doc_type": "regulation", "query": "1904.39"}))

    def test_the_same_call_gets_the_same_uuid_every_time(self) -> None:
        self.assertEqual(idempotency_key("s1", "evaluate_rule", {"rule_id": "R1"}),
                         idempotency_key("s1", "evaluate_rule", {"rule_id": "R1"}))

    def test_session_tool_and_arguments_each_change_the_key(self) -> None:
        base = idempotency_key("s1", "search_knowledge_base", {"query": "1904.39"})
        self.assertNotEqual(base, idempotency_key("s2", "search_knowledge_base", {"query": "1904.39"}))
        self.assertNotEqual(base, idempotency_key("s1", "evaluate_rule", {"query": "1904.39"}))
        self.assertNotEqual(base, idempotency_key("s1", "search_knowledge_base", {"query": "1904.7"}))

    def test_parts_cannot_run_together(self) -> None:
        # "a" + "b:c" and "a:b" + "c" must not collide once joined
        self.assertNotEqual(idempotency_key("a", "b:c", {}), idempotency_key("a:b", "c", {}))


if __name__ == "__main__":
    unittest.main()
