import unittest

from sixcat.run import choice_letter


class TestLetters(unittest.TestCase):
    def test_twelfth_choice_is_L(self):
        self.assertEqual(choice_letter(11), "L")

    def test_fifth_choice_is_E(self):
        self.assertEqual(choice_letter(4), "E")


if __name__ == "__main__":
    unittest.main()
