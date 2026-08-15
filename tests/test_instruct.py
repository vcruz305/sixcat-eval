import unittest

from sixcat.instruct import item_ok


class TestInstruct(unittest.TestCase):
    def test_no_comma_and_lowercase(self):
        item = {
            "prompt": "say hi",
            "instruction_id_list": ["punctuation:no_comma", "change_case:english_lowercase"],
            "kwargs": [{}, {}],
        }
        self.assertTrue(item_ok(item, "hello there friend"))
        self.assertFalse(item_ok(item, "hello, there"))
        self.assertFalse(item_ok(item, "Hello there"))


if __name__ == "__main__":
    unittest.main()
