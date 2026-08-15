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


if __name__ == "__main__":
    unittest.main()
