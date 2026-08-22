import unittest

from sixcat import instruct
from sixcat.dataio import read_jsonl


class TestInstruct(unittest.TestCase):
    def test_no_comma_and_lowercase(self):
        item = {
            "prompt": "say hi",
            "instruction_id_list": ["punctuation:no_comma", "change_case:english_lowercase"],
            "kwargs": [{}, {}],
        }
        self.assertTrue(instruct.item_ok(item, "hello there friend"))
        self.assertFalse(instruct.item_ok(item, "hello, there"))
        self.assertFalse(instruct.item_ok(item, "Hello there"))

    def test_unknown_and_malformed_instruction_sets_fail_closed(self):
        self.assertFalse(instruct.check_instruction("unknown:constraint", {}, "", "anything"))
        self.assertFalse(
            instruct.item_ok(
                {"prompt": "", "instruction_id_list": ["punctuation:no_comma"], "kwargs": []},
                "no comma",
            )
        )
        self.assertFalse(
            instruct.item_ok(
                {"prompt": "", "instruction_id_list": ["punctuation:no_comma"], "kwargs": [{}]},
                "",
            )
        )

    def test_all_shipped_instruction_ids_have_explicit_checkers(self):
        shipped = {
            instruction_id
            for row in read_jsonl("ifeval_100.jsonl")
            for instruction_id in row.get("instruction_id_list") or []
        }
        self.assertEqual(shipped - instruct.SUPPORTED_INSTRUCTION_IDS, set())

    def test_strict_relations_and_exact_bullet_count(self):
        check = instruct.check_instruction
        self.assertTrue(check("length_constraints:number_words", {"relation": "less than", "num_words": 3}, "", "one two"))
        self.assertFalse(check("length_constraints:number_words", {"relation": "less than", "num_words": 2}, "", "one two"))
        self.assertTrue(check("keywords:frequency", {"relation": "less than", "keyword": "cat", "frequency": 2}, "", "cat"))
        self.assertFalse(check("keywords:frequency", {"relation": "less than", "keyword": "cat", "frequency": 1}, "", "cat"))
        self.assertTrue(check("keywords:letter_frequency", {"let_relation": "at least", "letter": "!", "let_frequency": 2}, "", "yes!!"))
        self.assertFalse(check("keywords:letter_frequency", {"let_relation": "less than", "letter": "!", "let_frequency": 2}, "", "yes!!"))
        two = "* one\n* two"
        three = two + "\n* three"
        self.assertTrue(check("detectable_format:number_bullet_lists", {"num_bullets": 2}, "", two))
        self.assertFalse(check("detectable_format:number_bullet_lists", {"num_bullets": 2}, "", three))

    def test_missing_shipped_checker_types(self):
        check = instruct.check_instruction
        self.assertTrue(check("change_case:capital_word_frequency", {"capital_relation": "at least", "capital_frequency": 2}, "", "USA NASA launch"))
        self.assertFalse(check("change_case:capital_word_frequency", {"capital_relation": "less than", "capital_frequency": 2}, "", "USA NASA launch"))
        self.assertTrue(check("combination:two_responses", {}, "", "first response******second response"))
        self.assertFalse(check("combination:two_responses", {}, "", "same******same"))
        self.assertTrue(check("detectable_content:postscript", {"postscript_marker": "P.S."}, "", "Body\n\nP.S. note"))
        self.assertFalse(check("detectable_content:postscript", {"postscript_marker": "P.S."}, "", "Body only"))
        sections = "SECTION 1\nfirst\nSECTION 2\nsecond"
        self.assertTrue(check("detectable_format:multiple_sections", {"section_spliter": "SECTION", "num_sections": 2}, "", sections))
        self.assertFalse(check("detectable_format:multiple_sections", {"section_spliter": "SECTION", "num_sections": 3}, "", sections))

    def test_official_format_semantics(self):
        check = instruct.check_instruction
        self.assertTrue(check("length_constraints:number_paragraphs", {"num_paragraphs": 2}, "", "first\n***\nsecond"))
        self.assertFalse(check("length_constraints:number_paragraphs", {"num_paragraphs": 2}, "", "first\n\nsecond"))
        self.assertTrue(check("detectable_format:json_format", {}, "", "```json\n{\"ok\": true}\n```"))
        self.assertTrue(check("combination:repeat_prompt", {"prompt_to_repeat": "Say Hello"}, "", "say hello\nAnswer"))
        self.assertTrue(check("startend:end_checker", {"end_phrase": "Done."}, "", '"work. Done."'))

    def test_response_language_uses_real_detection(self):
        check = instruct.check_instruction
        samples = {
            "kn": "ಇದು ಕನ್ನಡ ಭಾಷೆಯಲ್ಲಿ ಬರೆಯಲಾದ ಸ್ಪಷ್ಟವಾದ ಉತ್ತರವಾಗಿದೆ.",
            "pa": "ਇਹ ਪੰਜਾਬੀ ਭਾਸ਼ਾ ਵਿੱਚ ਲਿਖਿਆ ਹੋਇਆ ਸਪਸ਼ਟ ਜਵਾਬ ਹੈ।",
            "mr": "हे उत्तर मराठी भाषेत स्पष्टपणे लिहिलेले आहे.",
            "fa": "این پاسخ روشن و کامل به زبان فارسی نوشته شده است.",
        }
        for language, text in samples.items():
            with self.subTest(language=language):
                self.assertTrue(check("language:response_language", {"language": language}, "", text))
                self.assertFalse(check("language:response_language", {"language": language}, "", "This is a generic English response."))

    def test_every_shipped_checker_has_positive_and_negative_receipts(self):
        cases = {
            "change_case:capital_word_frequency": (
                {"capital_relation": "at least", "capital_frequency": 2},
                "USA NASA launch",
                "USA launch",
            ),
            "change_case:english_capital": ({}, "THIS IS A CLEAR ENGLISH RESPONSE.", "This is mixed case."),
            "change_case:english_lowercase": ({}, "this is a clear english response.", "This is mixed case."),
            "combination:repeat_prompt": ({"prompt_to_repeat": "Say hello"}, "Say hello\nanswer", "answer only"),
            "combination:two_responses": ({}, "first******second", "first only"),
            "detectable_content:number_placeholders": ({"num_placeholders": 2}, "[name] [date]", "[name]"),
            "detectable_content:postscript": ({"postscript_marker": "P.S."}, "body\nP.S. note", "body"),
            "detectable_format:json_format": ({}, '{"ok": true}', "not json"),
            "detectable_format:multiple_sections": (
                {"section_spliter": "SECTION", "num_sections": 2},
                "SECTION 1\none\nSECTION 2\ntwo",
                "SECTION 1\none",
            ),
            "detectable_format:number_bullet_lists": ({"num_bullets": 2}, "* one\n* two", "* one"),
            "detectable_format:number_highlighted_sections": ({"num_highlights": 2}, "*one* and **two**", "*one*"),
            "detectable_format:title": ({}, "<<A title>>\nbody", "body"),
            "keywords:existence": ({"keywords": ["cat", "dog"]}, "cat and dog", "cat only"),
            "keywords:forbidden_words": ({"forbidden_words": ["bad"]}, "clean response", "bad response"),
            "keywords:frequency": ({"relation": "at least", "keyword": "cat", "frequency": 2}, "cat cat", "cat"),
            "keywords:letter_frequency": ({"let_relation": "at least", "letter": "!", "let_frequency": 2}, "yes!!", "yes!"),
            "language:response_language": (
                {"language": "kn"},
                "ಇದು ಕನ್ನಡ ಭಾಷೆಯಲ್ಲಿ ಬರೆಯಲಾದ ಸ್ಪಷ್ಟವಾದ ಉತ್ತರವಾಗಿದೆ.",
                "This is English.",
            ),
            "length_constraints:number_paragraphs": ({"num_paragraphs": 2}, "one\n***\ntwo", "one"),
            "length_constraints:number_sentences": ({"relation": "at least", "num_sentences": 2}, "One. Two.", "One."),
            "length_constraints:number_words": ({"relation": "at least", "num_words": 2}, "one two", "one"),
            "punctuation:no_comma": ({}, "no comma", "has, comma"),
            "startend:end_checker": ({"end_phrase": "Done."}, "work. Done.", "Done. extra"),
            "startend:quotation": ({}, '"quoted"', "unquoted"),
        }
        self.assertEqual(set(cases), instruct.SUPPORTED_INSTRUCTION_IDS)
        for instruction_id, (kwargs, passing, failing) in cases.items():
            with self.subTest(instruction_id=instruction_id, receipt="pass"):
                self.assertTrue(instruct.check_instruction(instruction_id, kwargs, "", passing))
            with self.subTest(instruction_id=instruction_id, receipt="fail"):
                self.assertFalse(instruct.check_instruction(instruction_id, kwargs, "", failing))


if __name__ == "__main__":
    unittest.main()
