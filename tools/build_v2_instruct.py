"""Deterministic builder for sixcat/data/v2_instruct.jsonl (challenge-v2 Instruct).

Twenty original prompts. Eighteen carry four to six machine-checkable
constraints; the two JSON items bundle theirs into one typed-shape check. Every item ships with a reference response in this file; the
builder refuses to write the data file unless each reference satisfies every
constraint of its item. That proves each item is satisfiable (the v1 set
inherits one IFEval item that no response can pass).

References are never written to the data file and are never shown to a model.

    python tools/build_v2_instruct.py            # rewrite the data file
    python tools/build_v2_instruct.py --check    # fail if the file differs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "sixcat" / "data" / "v2_instruct.jsonl"

DEFS = ("A \"line\" means a non-blank line of your response, and a \"word\" means a run of characters "
        "separated by spaces. ")

# (key, prompt, [(instruction_id, kwargs), ...], reference response)
ITEMS: list[tuple[str, str, list[tuple[str, dict]], str]] = [
    ("i01",
     "Write a product description for a reusable steel water bottle. " + DEFS +
     "Your response must have exactly 5 lines, and every line must have exactly 6 words. "
     "Do not use any uppercase letters. Do not use any commas. Include the word \"steel\".",
     [("v2:line_count", {"relation": "exactly", "n": 5}),
      ("v2:words_per_line", {"relation": "exactly", "n": 6}),
      ("v2:no_uppercase", {}),
      ("punctuation:no_comma", {}),
      ("keywords:existence", {"keywords": ["steel"]})],
     "this bottle keeps water cold longer\n"
     "made from strong brushed steel walls\n"
     "the lid seals tight every time\n"
     "it fits most car cup holders\n"
     "refill it and skip plastic waste"),

    ("i02",
     "Write a poem about the harvest season. " + DEFS +
     "It must have exactly 7 lines, and the first letters of the lines, read from top to bottom, "
     "must spell HARVEST. Every line must have at most 8 words and must end with a period. "
     "Do not use the words \"autumn\" or \"fall\" anywhere, not even inside a longer word.",
     [("v2:acrostic", {"word": "HARVEST"}),
      ("v2:line_count", {"relation": "exactly", "n": 7}),
      ("v2:words_per_line", {"relation": "at most", "n": 8}),
      ("v2:line_endings", {"suffix": "."}),
      ("keywords:forbidden_words", {"forbidden_words": ["autumn", "fall"]})],
     "Heavy apples bend the orchard boughs.\n"
     "A cold wind combs the yellow grass.\n"
     "Red leaves gather by the gate.\n"
     "Vines dry slowly on the stone.\n"
     "Every field is cut and bare.\n"
     "Smoke lifts from a distant chimney.\n"
     "The year exhales and settles down."),

    ("i03",
     "Invent a fictional novel and describe it. Respond with only a JSON object and nothing else. "
     "The object must have exactly these five keys: \"title\" (a string of at most 4 words), "
     "\"year\" (an integer from 1950 to 1999), \"genres\" (an array of exactly 3 strings, in "
     "alphabetical order), \"available\" (a boolean) and \"rating\" (an integer from 1 to 5).",
     [("v2:json_object", {"fields": {
         "title": {"type": "string", "max_words": 4},
         "year": {"type": "integer", "min": 1950, "max": 1999},
         "genres": {"type": "array", "length": 3, "items": {"type": "string"}, "sorted": True},
         "available": {"type": "boolean"},
         "rating": {"type": "integer", "min": 1, "max": 5}}})],
     '{"title": "The Glass Orchard", "year": 1987, "genres": ["fantasy", "mystery", "romance"], '
     '"available": true, "rating": 4}'),

    ("i04",
     "Explain what a hash table is. " + DEFS +
     "Your response must be exactly 40 words long and must consist of exactly 2 sentences. "
     "Include both of the words \"bucket\" and \"collision\". Do not use any digits.",
     [("v2:word_count", {"relation": "exactly", "n": 40}),
      ("length_constraints:number_sentences", {"relation": "at least", "num_sentences": 2}),
      ("length_constraints:number_sentences", {"relation": "less than", "num_sentences": 3}),
      ("keywords:existence", {"keywords": ["bucket", "collision"]}),
      ("v2:forbidden_chars", {"chars": "0123456789"})],
     "A hash table stores key value pairs by running each key through a function that picks a "
     "bucket in an array. When two keys land in one bucket a collision occurs and the table "
     "resolves it by chaining or probing."),

    ("i05",
     "Give five tips for getting better rest at night. " + DEFS +
     "Write exactly 5 lines, one tip per line. The first line must have exactly 3 words, and each "
     "later line must have exactly one more word than the line before it. Use no uppercase "
     "letters and no punctuation marks of any kind. Do not use the word \"sleep\".",
     [("v2:line_count", {"relation": "exactly", "n": 5}),
      ("v2:word_ladder", {"start": 3, "step": 1}),
      ("v2:no_uppercase", {}),
      ("v2:forbidden_chars", {"chars": ".,;:!?'\"-()"}),
      ("keywords:forbidden_words", {"forbidden_words": ["sleep"]})],
     "dim the lights\n"
     "keep your room cool\n"
     "put the phone away early\n"
     "avoid heavy meals late at night\n"
     "wake at the same hour every morning"),

    ("i06",
     "Write one sentence about sailors. " + DEFS +
     "The sentence must be exactly 8 words long, every word must begin with the letter s, and the "
     "sentence must end with a period. Put it on a single line.",
     [("v2:word_count", {"relation": "exactly", "n": 8}),
      ("v2:alliteration", {"letter": "s"}),
      ("v2:line_count", {"relation": "exactly", "n": 1}),
      ("v2:line_endings", {"suffix": "."})],
     "Seven salty sailors sang sweet songs since sunrise."),

    ("i07",
     "Summarize how a proposal becomes binding in a typical parliament. "
     "Write exactly 3 paragraphs, separated by blank lines, with at most 90 words in total. "
     "The very first word of your response must be \"First\". The words \"committee\", \"debate\", "
     "\"vote\" and \"signature\" must all appear, and the first time each one appears must follow "
     "that order. Do not use the word \"government\".",
     [("v2:paragraphs", {"n": 3}),
      ("v2:word_count", {"relation": "at most", "n": 90}),
      ("v2:nth_word", {"n": 1, "word": "First"}),
      ("v2:required_order", {"terms": ["committee", "debate", "vote", "signature"]}),
      ("keywords:forbidden_words", {"forbidden_words": ["government"]})],
     "First a member drafts the proposal and hands it to a committee that studies every clause.\n\n"
     "Next the full chamber holds a debate where members argue and offer changes before a vote "
     "is taken.\n\n"
     "Finally the approved text goes to the head of state whose signature turns the proposal "
     "into binding rules."),

    ("i08",
     "Write a safety notice for a school chemistry lab. " + DEFS +
     "It must have exactly 4 lines. Every line must begin with the word RULE and have at most "
     "7 words. Do not use any lowercase letters or any exclamation marks. Mention goggles.",
     [("v2:line_count", {"relation": "exactly", "n": 4}),
      ("v2:line_starts", {"prefix": "RULE"}),
      ("v2:words_per_line", {"relation": "at most", "n": 7}),
      ("v2:no_lowercase", {}),
      ("v2:forbidden_chars", {"chars": "!"}),
      ("keywords:existence", {"keywords": ["goggles"]})],
     "RULE ONE: WEAR GOGGLES AT ALL TIMES\n"
     "RULE TWO: NEVER TASTE ANY CHEMICAL\n"
     "RULE THREE: LABEL EVERY BOTTLE YOU FILL\n"
     "RULE FOUR: WASH HANDS BEFORE YOU LEAVE"),

    ("i09",
     "Describe a small grocery trip. Your response must be exactly 2 sentences and at most 30 "
     "words. It must contain exactly three whole numbers written with digits (no decimals), and "
     "those three numbers must add up to exactly 100. No other digits may appear anywhere. Do not "
     "use the $ symbol.",
     [("v2:integers_sum", {"count": 3, "total": 100}),
      ("length_constraints:number_sentences", {"relation": "at least", "num_sentences": 2}),
      ("length_constraints:number_sentences", {"relation": "less than", "num_sentences": 3}),
      ("v2:word_count", {"relation": "at most", "n": 30}),
      ("v2:forbidden_chars", {"chars": "$"})],
     "Fruit cost 45 and bread cost 30 this week. Cheese took the remaining 25 of my budget."),

    ("i10",
     "Describe a thunderstorm. " + DEFS +
     "Your response must be a single line of exactly 25 words, and no word may be used more than "
     "once (ignoring capitalization). Do not use any commas. Include the word \"lightning\".",
     [("v2:word_count", {"relation": "exactly", "n": 25}),
      ("v2:unique_words", {}),
      ("v2:line_count", {"relation": "exactly", "n": 1}),
      ("punctuation:no_comma", {}),
      ("keywords:existence", {"keywords": ["lightning"]})],
     "dark clouds gather above quiet hills while distant lightning splits heavy air then rolling "
     "booms shake windows as cold rain hammers every rooftop until dawn"),

    ("i11",
     "Describe a city at night. " + DEFS +
     "Write exactly 3 lines, each with at least 6 words. You must not use the letter e anywhere "
     "in your response, in either uppercase or lowercase. Include the word \"taxi\".",
     [("v2:line_count", {"relation": "exactly", "n": 3}),
      ("v2:words_per_line", {"relation": "at least", "n": 6}),
      ("keywords:letter_frequency", {"letter": "e", "let_relation": "less than", "let_frequency": 1}),
      ("keywords:existence", {"keywords": ["taxi"]})],
     "a taxi hums along a dark and vacant road\n"
     "shop signs glow pink and gold through thin fog\n"
     "a full moon hangs high and still on rooftops"),

    ("i12",
     "List six fruits. " + DEFS +
     "Write exactly 6 lines. Each line must have exactly 3 words: the name of a fruit followed by "
     "two words that describe it. The lines must be in alphabetical order by fruit name. Use no "
     "uppercase letters. Do not use \"apple\" or \"banana\".",
     [("v2:line_count", {"relation": "exactly", "n": 6}),
      ("v2:words_per_line", {"relation": "exactly", "n": 3}),
      ("v2:alphabetical_lines", {}),
      ("v2:no_uppercase", {}),
      ("keywords:forbidden_words", {"forbidden_words": ["apple", "banana"]})],
     "cherry small tart\n"
     "fig soft sweet\n"
     "grape juicy round\n"
     "lemon sour bright\n"
     "mango rich golden\n"
     "peach fuzzy fragrant"),

    ("i13",
     "Write release notes for version 2.0 of a note-taking app. Start with a title wrapped in "
     "double angular brackets, like <<title>>. Include exactly 4 bullet points in Markdown, each "
     "on its own line beginning with a hyphen. Highlight at least 2 phrases with Markdown "
     "emphasis, like *this*. Finish with a postscript that begins with P.S. Keep the whole "
     "response under 80 words, and do not use the word \"bug\", not even inside a longer word.",
     [("detectable_format:title", {}),
      ("detectable_format:number_bullet_lists", {"num_bullets": 4}),
      ("detectable_format:number_highlighted_sections", {"num_highlights": 2}),
      ("detectable_content:postscript", {"postscript_marker": "P.S."}),
      ("length_constraints:number_words", {"relation": "less than", "num_words": 80}),
      ("keywords:forbidden_words", {"forbidden_words": ["bug"]})],
     "<<Notes 2.0 Release>>\n\n"
     "- Added *dark mode* for late sessions\n"
     "- Search is now *twice as fast*\n"
     "- Folders can be nested freely\n"
     "- Export supports plain text\n\n"
     "P.S. Thank you for the feedback."),

    ("i14",
     "Write a dialogue between a customer and a barista. " + DEFS +
     "It must have exactly 6 lines. The lines must alternate speakers, starting with the "
     "customer: each of the customer's lines must begin with \"Customer:\" and each of the "
     "barista's lines with \"Barista:\". Every line must have at most 10 words, counting the "
     "speaker label as a word. The word \"oat\" must appear, and the very last character of your "
     "response must be a question mark.",
     [("v2:line_count", {"relation": "exactly", "n": 6}),
      ("v2:alternating_prefixes", {"prefixes": ["Customer:", "Barista:"]}),
      ("v2:words_per_line", {"relation": "at most", "n": 10}),
      ("keywords:existence", {"keywords": ["oat"]}),
      ("startend:end_checker", {"end_phrase": "?"})],
     "Customer: Hi, could I get a latte?\n"
     "Barista: Sure, which milk would you like?\n"
     "Customer: Do you have oat milk today?\n"
     "Barista: We do, and it is free.\n"
     "Customer: Great, one large oat latte then.\n"
     "Barista: Coming right up, anything else today?"),

    ("i15",
     "Explain how to make a pot of tea. Respond with only a JSON object and nothing else. "
     "The object must have exactly two keys: \"steps\", an array of exactly 4 strings where each "
     "string has at most 6 words, and \"minutes\", an integer from 10 to 20. "
     "The word \"boil\" must appear somewhere in your response.",
     [("v2:json_object", {"fields": {
         "steps": {"type": "array", "length": 4, "items": {"type": "string", "max_words": 6}},
         "minutes": {"type": "integer", "min": 10, "max": 20}}}),
      ("keywords:existence", {"keywords": ["boil"]})],
     '{"steps": ["boil fresh water", "warm the pot", "steep leaves four minutes", "pour and enjoy"], '
     '"minutes": 12}'),

    ("i16",
     "Invent three people and write them as records. " + DEFS +
     "Write exactly 3 lines and nothing else. Each line must have the form Name|Age|City with no "
     "spaces: Name and City are each a single word made of one capital letter followed by "
     "lowercase letters, and Age is a two-digit number. The lines must be in alphabetical order "
     "by Name, and the three ages must add up to exactly 100.",
     [("v2:line_count", {"relation": "exactly", "n": 3}),
      ("v2:line_regex", {"pattern": "[A-Z][a-z]+\\|[0-9]{2}\\|[A-Z][a-z]+"}),
      ("v2:alphabetical_lines", {}),
      ("v2:integers_sum", {"count": 3, "total": 100})],
     "Ada|41|Lyon\n"
     "Ben|33|Oslo\n"
     "Cleo|26|Rome"),

    ("i17",
     "Write a short email politely declining a meeting invitation. Your response must begin with "
     "exactly \"Dear Ms. Okafor,\" and must end with exactly \"Regards, Sam\". It must have "
     "exactly 3 paragraphs separated by blank lines (the greeting and the sign-off each count as "
     "a paragraph) and at most 70 words in total. Mention Thursday. Do not use the words "
     "\"sorry\" or \"unfortunately\".",
     [("v2:starts_with", {"text": "Dear Ms. Okafor,"}),
      ("startend:end_checker", {"end_phrase": "Regards, Sam"}),
      ("v2:paragraphs", {"n": 3}),
      ("v2:word_count", {"relation": "at most", "n": 70}),
      ("keywords:existence", {"keywords": ["Thursday"]}),
      ("keywords:forbidden_words", {"forbidden_words": ["sorry", "unfortunately"]})],
     "Dear Ms. Okafor,\n\n"
     "Thank you for the invitation to the planning session. I have a prior commitment at that "
     "time and cannot attend, though I would be glad to join if it moves to Thursday.\n\n"
     "Regards, Sam"),

    ("i18",
     "Explain to a young child why things drop to the ground. " + DEFS +
     "Use only words that are at most 5 letters long. Write exactly 3 sentences and at least 25 "
     "words. Do not use the word \"force\".",
     [("v2:max_word_length", {"n": 5}),
      ("length_constraints:number_sentences", {"relation": "at least", "num_sentences": 3}),
      ("length_constraints:number_sentences", {"relation": "less than", "num_sentences": 4}),
      ("length_constraints:number_words", {"relation": "at least", "num_words": 25}),
      ("keywords:forbidden_words", {"forbidden_words": ["force"]})],
     "Big rocks like Earth pull small stuff down to them. That is why a ball you toss up comes "
     "back to your hand. The moon stays near us for the same cause."),

    ("i19",
     "Give two different slogans for a bicycle shop. Separate the two slogans with a line "
     "containing exactly six asterisks (******) and write nothing else. Use no uppercase letters "
     "and no exclamation marks. The two slogans together must have at most 12 words, and the word "
     "\"ride\" must appear.",
     [("combination:two_responses", {}),
      ("v2:no_uppercase", {}),
      ("v2:forbidden_chars", {"chars": "!"}),
      ("v2:word_count", {"relation": "at most", "n": 12}),
      ("keywords:existence", {"keywords": ["ride"]})],
     "ride farther smile wider\n"
     "******\n"
     "your next ride starts here"),

    ("i20",
     "Write an announcement for a library book sale. It must be at most 140 characters long and "
     "at least 15 words long. It must mention the date \"March 9\", contain exactly one "
     "exclamation mark, and end with the hashtag #BookSale as its very last characters.",
     [("v2:char_count", {"relation": "at most", "n": 140}),
      ("length_constraints:number_words", {"relation": "at least", "num_words": 15}),
      ("keywords:existence", {"keywords": ["March 9"]}),
      ("v2:char_occurrences", {"char": "!", "n": 1}),
      ("startend:end_checker", {"end_phrase": "#BookSale"})],
     "Our library book sale returns on March 9 with thousands of gently used titles at tiny "
     "prices, so bring a bag! #BookSale"),
]


def rows() -> list[dict]:
    return [{"key": key, "prompt": prompt,
             "instruction_id_list": [inst_id for inst_id, _ in constraints],
             "kwargs": [kwargs for _, kwargs in constraints]}
            for key, prompt, constraints, _ in ITEMS]


def references() -> dict[str, str]:
    return {key: reference for key, _, _, reference in ITEMS}


def verify() -> None:
    from sixcat.v2_instruct import failed_constraints

    refs = references()
    for row in rows():
        failed = failed_constraints(row, refs[row["key"]])
        if failed:
            raise AssertionError(f"{row['key']}: reference fails {failed}")
        if not failed_constraints(row, "I cannot help with that."):
            raise AssertionError(f"{row['key']}: a refusal must not satisfy the item")


def render() -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify the shipped file instead of writing it")
    args = parser.parse_args(argv)
    verify()
    text = render()
    if args.check:
        if OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} differs from the builder output", file=sys.stderr)
            return 1
        print(f"{OUT.name}: up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(ITEMS)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
