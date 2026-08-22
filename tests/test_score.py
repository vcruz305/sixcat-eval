import unittest

from sixcat.score import category_score, extract_gsm_number, extract_mc_letter, overall_score


class TestScore(unittest.TestCase):
    def test_overall_is_unweighted_mean_of_six_categories(self):
        cats = {
            "knowledge": 80.0,
            "math": 50.0,
            "truth": 70.0,
            "instruct": 40.0,
            "code": 20.0,
            "tools": 60.0,
        }
        self.assertAlmostEqual(overall_score(cats), 53.3333333333, places=6)

    def test_overall_requires_all_six_keys(self):
        with self.assertRaises(KeyError):
            overall_score({"knowledge": 100.0})

    def test_overall_skips_none_then_still_needs_six_present(self):
        cats = {
            "knowledge": 80.0,
            "math": None,
            "truth": 70.0,
            "instruct": 40.0,
            "code": 20.0,
            "tools": 60.0,
        }
        # math missing: average the five that ran
        self.assertAlmostEqual(overall_score(cats), (80 + 70 + 40 + 20 + 60) / 5)

    def test_category_score_is_percent(self):
        rows = [{"ok": True}, {"ok": True}, {"ok": False}, {"ok": False}]
        self.assertEqual(category_score(rows), 50.0)

    def test_empty_category_is_none_not_zero(self):
        self.assertIsNone(category_score([]))

    def test_extract_mc_letter(self):
        self.assertEqual(extract_mc_letter("The answer is B."), "B")
        self.assertEqual(extract_mc_letter("D"), "D")
        self.assertEqual(extract_mc_letter("I think (C) is correct"), "C")

    def test_extract_gsm_number(self):
        self.assertEqual(extract_gsm_number("... #### 29"), "29")
        self.assertEqual(extract_gsm_number("The total is 1,240 dollars."), "1240")

    def test_arc_gold_resolves_dataset_labels_to_presented_choice_letters(self):
        from sixcat.run import arc_answer_letter

        self.assertEqual(arc_answer_letter({"labels": ["1", "2", "3", "4"], "answer": "3"}), "C")
        self.assertEqual(arc_answer_letter({"labels": ["A", "B", "C", "D"], "answer": "B"}), "B")
        self.assertEqual(arc_answer_letter({"labels": ["A", "B", "C", "D", "E"], "answer": "E"}), "E")
        with self.assertRaises(ValueError):
            arc_answer_letter({"labels": ["A", "B"], "answer": "C"})

    def test_run_knowledge_scores_numeric_arc_labels_end_to_end(self):
        from unittest.mock import patch

        from sixcat.run import run_knowledge

        item = {
            "question": "pick third",
            "texts": ["one", "two", "three", "four"],
            "labels": ["1", "2", "3", "4"],
            "answer": "3",
        }

        class Policy:
            budgets = {"knowledge": 32}

        class Client:
            policy = Policy()

            def complete(self, prompt, **kwargs):
                return {
                    "text": "C",
                    "finish": "stop",
                    "usage": {"completion_tokens": 1, "prompt_tokens": 8},
                    "request_params": kwargs,
                }

        def fake_data(name):
            return [item] if name == "tiny_arc.jsonl" else []

        with patch("sixcat.run.read_jsonl", side_effect=fake_data):
            rows = run_knowledge(Client(), limit=None)

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["ok"])
        self.assertEqual(rows[0]["pred"], "C")
        self.assertEqual(rows[0]["gold"], "C")

    def test_knowledge_limit_is_total_for_category_not_repeated_per_dataset(self):
        from unittest.mock import patch

        from sixcat.run import run_knowledge

        datasets = {
            "tiny_mmlu.jsonl": [
                {"question": f"mmlu {i}", "choices": ["yes", "no"], "answer": 0}
                for i in range(20)
            ],
            "tiny_arc.jsonl": [
                {
                    "question": f"arc {i}",
                    "texts": ["yes", "no"],
                    "labels": ["A", "B"],
                    "answer": "A",
                }
                for i in range(20)
            ],
            "tiny_hellaswag.jsonl": [
                {"ctx": f"hellaswag {i}", "endings": ["yes", "no"], "answer": 0}
                for i in range(20)
            ],
            "tiny_winogrande.jsonl": [
                {
                    "sentence": f"winogrande {i} _",
                    "option1": "yes",
                    "option2": "no",
                    "answer": "1",
                }
                for i in range(20)
            ],
        }

        prompts = []

        class Client:
            def complete(self, prompt, max_tokens):
                prompts.append(prompt)
                return {
                    "text": "A",
                    "finish": "stop",
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    "request_params": {"max_tokens": max_tokens},
                }

        with patch("sixcat.run.read_jsonl", side_effect=lambda name: datasets[name]):
            rows = run_knowledge(Client(), limit=20)

        self.assertEqual(len(rows), 20)
        self.assertEqual(
            {
                "mmlu": sum(prompt.startswith("mmlu ") for prompt in prompts),
                "arc": sum(prompt.startswith("arc ") for prompt in prompts),
                "hellaswag": sum(prompt.startswith("hellaswag ") for prompt in prompts),
                "winogrande": sum(prompt.startswith("winogrande ") for prompt in prompts),
            },
            {"mmlu": 5, "arc": 5, "hellaswag": 5, "winogrande": 5},
        )

    def test_small_knowledge_limit_still_spans_multiple_datasets(self):
        from sixcat.run import split_category_limit

        self.assertEqual(split_category_limit(3, 4), [1, 1, 1, 0])


if __name__ == "__main__":
    unittest.main()
