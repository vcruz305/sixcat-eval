"""Deterministic builder for sixcat/data/v2_math.jsonl (challenge-v2 Math).

Twenty original problems in four tiers of five:

  tier 1  long multi-step word problems with distractors
  tier 2  rates, mixtures, work-backwards and linear systems
  tier 3  counting, number theory and lattice paths
  tier 4  probability and long exact simulation

Every answer is computed by code, and wherever a second method exists the answer
is cross-checked by brute force or simulation before the row is emitted. Nothing
here is copied from GSM8K or any other dataset.

    python tools/build_v2_math.py            # rewrite the data file
    python tools/build_v2_math.py --check    # fail if the file differs

A private LCG is used instead of `random` so the output cannot drift between
Python versions.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "sixcat" / "data" / "v2_math.jsonl"
BASE_SEED = 20261122
MASK = (1 << 64) - 1


class LCG:
    def __init__(self, seed: int) -> None:
        self.state = seed & MASK

    def _next(self) -> int:
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) & MASK
        return self.state >> 33

    def randint(self, low: int, high: int) -> int:
        return low + self._next() % (high - low + 1)

    def choice(self, values):
        return values[self._next() % len(values)]


class Retry(Exception):
    """Parameters do not give a clean instance; draw again."""


def money(value: Fraction) -> str:
    cents = value * 100
    if cents.denominator != 1:
        raise Retry
    whole, part = divmod(int(cents), 100)
    return f"{whole}.{part:02d}" if part else str(whole)


def number(value) -> str:
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    scaled = value * 100
    if scaled.denominator != 1:
        raise Retry
    text = f"{int(scaled) // 100}.{int(scaled) % 100:02d}"
    return text.rstrip("0").rstrip(".")


def comma(value: int) -> str:
    return f"{value:,}"


# ----------------------------------------------------------------------------- tier 1

def m01(rng: LCG):
    booklets = rng.randint(55, 95)
    pages_each = rng.choice([32, 36, 40, 48])
    discount = rng.choice([5, 8, 10, 12])
    tax = rng.choice([4, 5, 6, 8])
    delivery = rng.choice([15, 20, 25, 35])
    pages = booklets * pages_each
    if pages <= 2000:
        raise Retry
    printing = (Fraction(12, 100) * 500 + Fraction(9, 100) * 1500 + Fraction(7, 100) * (pages - 2000))
    subtotal = printing + Fraction(7, 2) * booklets
    if abs(subtotal - 500) < 5:
        raise Retry
    discounted = subtotal * (1 - Fraction(discount, 100)) if subtotal > 500 else subtotal
    total = discounted * (1 + Fraction(tax, 100)) + delivery
    question = (
        f"A print shop charges $0.12 per page for the first 500 pages of an order, $0.09 per page for "
        f"pages 501 through 2,000, and $0.07 per page for every page after page 2,000. Binding costs "
        f"$3.50 per booklet. A school orders {booklets} booklets of {pages_each} pages each as a single "
        f"order. If the subtotal (printing plus binding) is more than $500, the shop takes {discount}% off "
        f"the subtotal. Sales tax of {tax}% is then charged on the amount after any discount, and a flat "
        f"${delivery} delivery fee is added after tax (the delivery fee is not taxed). The shop's van can "
        f"carry 40 boxes of 50 booklets each. What is the total amount the school pays, in dollars?"
    )
    return question, money(total)


def m02(rng: LCG):
    wage = rng.randint(18, 32)
    week1 = rng.randint(44, 52)
    sunday = rng.randint(3, 6)
    week2 = rng.randint(33, 39)
    withheld = rng.choice([12, 15, 18, 20])
    fee = rng.choice([25, 30, 35, 40])
    gross = (40 * wage + Fraction(3, 2) * wage * (week1 - 40) + 2 * wage * sunday) + week2 * wage
    net = gross * (1 - Fraction(withheld, 100)) - fee
    question = (
        f"Dana earns ${wage} per hour. In any week, hours worked Monday through Saturday beyond the "
        f"first 40 are paid at 1.5 times her hourly rate. Hours worked on a Sunday are paid at double "
        f"her hourly rate and do not count toward the 40-hour threshold. In week one she works "
        f"{week1} hours Monday through Saturday and {sunday} hours on Sunday. In week two she works "
        f"{week2} hours Monday through Saturday and does not work on Sunday. {withheld}% of her total "
        f"gross pay for the two weeks is withheld for taxes, and after that a ${fee} union fee is "
        f"deducted. Her coworker Sam earns $2 more per hour than Dana. How many dollars does Dana take "
        f"home for the two weeks?"
    )
    return question, money(net)


def _tank_time(capacity, start, rate_a, rate_b, b_on_at, drain, drain_level):
    """Exact event simulation. Returns (time, order of events)."""
    level, now = Fraction(start), Fraction(0)
    b_on = drain_open = False
    order = []
    for _ in range(10):
        rate = Fraction(rate_a) + (rate_b if b_on else 0) - (drain if drain_open else 0)
        if rate <= 0:
            raise Retry
        candidates = [("full", (capacity - level) / rate)]
        if not b_on:
            candidates.append(("b_on", Fraction(b_on_at) - now))
        if not drain_open:
            candidates.append(("drain", (drain_level - level) / rate))
        candidates = [(name, wait) for name, wait in candidates if wait >= 0]
        name, wait = min(candidates, key=lambda pair: pair[1])
        if sum(1 for _, other in candidates if other == wait) > 1:
            raise Retry  # simultaneous events would make the wording ambiguous
        level += rate * wait
        now += wait
        order.append(name)
        if name == "full":
            return now, order
        if name == "b_on":
            b_on = True
        else:
            drain_open = True
    raise Retry


def m03(rng: LCG):
    capacity = rng.choice([2400, 3000, 3600, 4200])
    start = rng.choice([200, 300, 360, 480])
    rate_a = rng.choice([36, 40, 45, 48])
    rate_b = rng.choice([24, 30, 36])
    b_on_at = rng.choice([10, 12, 15, 18])
    drain = rng.choice([12, 15, 18, 21])
    drain_level = rng.choice([1200, 1500, 1800])
    if drain_level >= capacity - 300:
        raise Retry
    time, order = _tank_time(capacity, start, rate_a, rate_b, b_on_at, drain, drain_level)
    if order != ["b_on", "drain", "full"] or time.denominator != 1:
        raise Retry
    question = (
        f"A water tank holds {comma(capacity)} liters and starts with {start} liters in it. Pump A adds "
        f"{rate_a} liters per minute and runs the whole time. Pump B adds {rate_b} liters per minute but "
        f"only switches on {b_on_at} minutes after the start, and then stays on. A drain removes "
        f"{drain} liters per minute; it is closed at first, opens at the moment the water level first "
        f"reaches {comma(drain_level)} liters, and stays open from then on. The tank is 3 meters tall. "
        f"How many minutes after the start does the tank become completely full?"
    )
    return question, number(time)


def m04(rng: LCG):
    batches = rng.randint(9, 20)
    servings = 8 * batches
    milk_on_hand = rng.choice([250, 400, 600, 750])
    eggs_on_hand = rng.choice([5, 7, 10])
    milk_price = rng.choice([Fraction(129, 100), Fraction(149, 100), Fraction(179, 100)])
    egg_price = rng.choice([Fraction(325, 100), Fraction(375, 100), Fraction(420, 100)])
    milk_needed = 360 * batches - milk_on_hand
    eggs_needed = 3 * batches - eggs_on_hand
    if milk_needed % 1000 == 0 or eggs_needed % 12 == 0:
        raise Retry
    cartons_milk = -(-milk_needed // 1000)
    cartons_eggs = -(-eggs_needed // 12)
    total = cartons_milk * milk_price + cartons_eggs * egg_price
    question = (
        f"A recipe that makes 8 servings needs 1.5 cups of milk and 3 eggs. A caterer must make "
        f"{servings} servings and scales the recipe exactly. Use 1 cup = 240 mL. The caterer already "
        f"has {milk_on_hand} mL of milk and {eggs_on_hand} eggs. Milk is sold only in 1-liter cartons "
        f"at ${money(milk_price)} each, and eggs only in cartons of 12 at ${money(egg_price)} each. The "
        f"recipe also needs salt, which the caterer has plenty of. The caterer buys the smallest "
        f"number of whole cartons of each that is enough. How many dollars does the caterer spend?"
    )
    return question, money(total)


def m05(rng: LCG):
    start = rng.randint(40, 90) * 10
    arrive = rng.randint(10, 30) * 10
    percent = rng.choice([20, 25, 40])
    defective = rng.randint(12, 48)
    returned = rng.randint(15, 60)
    stock = Fraction(start)
    for day in range(5):
        stock += arrive
        shipped = stock * percent / 100
        if shipped.denominator != 1:
            raise Retry
        stock -= shipped
        if day == 2:
            stock -= defective
    stock += returned
    question = (
        f"A warehouse has {start} units in stock before opening on Monday. On each of the five days "
        f"Monday through Friday, the same thing happens: first a delivery of {arrive} units arrives, "
        f"and then the warehouse ships out exactly {percent}% of the units it has on hand at that "
        f"moment. On Wednesday, after that day's shipment has gone out, {defective} units are found "
        f"to be defective and are thrown away. On Friday evening, after that day's shipment, "
        f"{returned} units shipped earlier in the week are returned and put back in stock. The "
        f"warehouse employs 14 people. How many units are in stock at the end of Friday?"
    )
    return question, number(stock)


# ----------------------------------------------------------------------------- tier 2

_FRACTION_WORDS = {Fraction(1, 2): "half", Fraction(1, 3): "one third", Fraction(1, 4): "one quarter",
                   Fraction(1, 5): "one fifth", Fraction(2, 5): "two fifths"}


def m06(rng: LCG):
    fractions = [rng.choice(list(_FRACTION_WORDS)) for _ in range(3)]
    extras = [rng.randint(3, 12) for _ in range(3)]
    refund = rng.choice([10, 15, 20, 25])
    start = rng.randint(30, 90) * 12
    money_left = Fraction(start)
    for part, extra in zip(fractions, extras):
        money_left = money_left - money_left * part - extra
        if money_left.denominator != 1 or money_left <= 20:
            raise Retry
    final = money_left + refund
    # Independent check: invert the chain from the final amount.
    back = final - refund
    for part, extra in reversed(list(zip(fractions, extras))):
        back = (back + extra) / (1 - part)
    assert back == start
    words = [_FRACTION_WORDS[part] for part in fractions]
    question = (
        f"Lena went shopping with a certain amount of money. At the first shop she spent {words[0]} "
        f"of the money she had, plus ${extras[0]} more. At the second shop she spent {words[1]} of "
        f"the money she had left at that point, plus ${extras[1]} more. At the third shop she spent "
        f"{words[2]} of what she then had left, plus ${extras[2]} more. On the way home she was given "
        f"a ${refund} refund for an item she had returned the week before. She arrived home with "
        f"${number(final)}. How many dollars did she have when she set out?"
    )
    return question, number(start)


def m07(rng: LCG):
    distance = rng.randint(30, 60) * 10
    freight_first = rng.choice([48, 54, 60, 66, 72])
    freight_after = rng.choice([36, 40, 45, 50])
    passenger = rng.choice([80, 90, 96, 100, 108])
    delay = rng.choice([15, 20, 30, 40])
    resume = Fraction(4, 3)                      # hours after 8:00 when the freight moves again
    passenger_start = Fraction(delay, 60)
    gap_at_resume = distance - freight_first - passenger * (resume - passenger_start)
    if gap_at_resume <= 0:
        raise Retry                              # they would meet before the freight resumes
    meet = resume + gap_at_resume / (freight_after + passenger)
    from_a = freight_first + freight_after * (meet - resume)
    if from_a.denominator != 1:
        raise Retry
    assert from_a + passenger * (meet - passenger_start) == distance
    question = (
        f"Towns A and B are {distance} km apart on a straight railway. A freight train leaves A "
        f"toward B at 8:00 at {freight_first} km/h. A passenger train leaves B toward A at "
        f"8:{delay:02d} at a constant {passenger} km/h. After the freight train has been moving for "
        f"exactly 1 hour, it stops for 20 minutes, and then continues toward B at {freight_after} km/h. "
        f"How many kilometers from A are the two trains when they meet?"
    )
    return question, number(from_a)


def m08(rng: LCG):
    volume = rng.choice([60, 80, 100, 120])
    strength = rng.choice([30, 40, 45, 60])
    first_out = rng.choice([12, 15, 20, 24])
    second_out = rng.choice([10, 16, 18, 25])
    added_strength = rng.choice([70, 75, 80, 90])
    if first_out >= volume or second_out >= volume:
        raise Retry
    acid = Fraction(volume * strength, 100)
    acid -= acid * Fraction(first_out, volume)
    acid -= acid * Fraction(second_out, volume)
    acid += Fraction(second_out * added_strength, 100)
    answer = number(acid)
    if "." not in answer:
        raise Retry
    question = (
        f"A vat contains {volume} liters of a solution that is {strength}% acid by volume. First, "
        f"{first_out} liters of the solution are drained off and replaced with {first_out} liters of "
        f"pure water, and the vat is stirred until uniform. Then {second_out} liters of the new "
        f"mixture are drained off and replaced with {second_out} liters of a solution that is "
        f"{added_strength}% acid. How many liters of pure acid are in the vat at the end?"
    )
    return question, answer


def m09(rng: LCG):
    cal = rng.randint(7, 15)
    past = rng.randint(2, cal - 3)
    k1 = rng.randint(2, 4)
    ahead = rng.randint(3, 9)
    k2 = rng.randint(2, 3)
    ana = k1 * (cal - past) + past
    ben = k2 * (cal + ahead) - ahead
    if not (cal < ana <= 70 and cal < ben <= 70) or ana == ben:
        raise Retry
    total = ana + ben + cal
    solutions = [(a, b, c) for c in range(past + 1, 100) for a in [k1 * (c - past) + past]
                 for b in [k2 * (c + ahead) - ahead] if a + b + c == total]
    assert solutions == [(ana, ben, cal)]
    times = {2: "twice", 3: "three times", 4: "four times"}
    question = (
        f"{past} years ago, Ana was {times[k1]} as old as Cal was then. {ahead} years from now, Ben "
        f"will be {times[k2]} as old as Cal will be then. The sum of the current ages of Ana, Ben and "
        f"Cal is {total}. How old is Ana now?"
    )
    return question, number(ana)


def m10(rng: LCG):
    a, b, c = rng.choice([(12, 18, 36), (10, 15, 30), (12, 24, 16), (15, 20, 12), (18, 24, 36), (20, 30, 12)])
    together = rng.randint(2, 4)
    second = rng.randint(1, 3)
    done = together * (Fraction(1, a) + Fraction(1, b))
    done += second * (Fraction(1, b) + Fraction(1, c))
    if done >= 1:
        raise Retry
    last = (1 - done) / (Fraction(1, 2 * b) + Fraction(1, c))
    total = together + second + last
    if total.denominator != 1:
        raise Retry
    question = (
        f"Working alone at a steady rate, crew A could pave a certain road in {a} days, crew B in "
        f"{b} days, and crew C in {c} days. Crews A and B start the job together. After {together} "
        f"full days, crew A leaves for good and crew C joins crew B. After {second} more full "
        f"day{'s' if second != 1 else ''}, some of crew B's equipment fails, and from then on crew B "
        f"works at half of its normal rate while crew C continues normally. How many days does the "
        f"whole job take from start to finish?"
    )
    return question, number(total)


# ----------------------------------------------------------------------------- tier 3

def m11(rng: LCG):
    upper = rng.randint(2100, 8900)
    a, b, c = rng.choice([(6, 10, 15), (4, 14, 21), (9, 12, 8), (6, 15, 4), (8, 12, 9)])
    count = sum(1 for n in range(1, upper + 1) if (n % a == 0 or n % b == 0) and n % c != 0)
    lcm = math.lcm
    formula = (upper // a + upper // b - upper // lcm(a, b)
               - upper // lcm(a, c) - upper // lcm(b, c) + upper // lcm(a, b, c))
    assert count == formula
    question = (
        f"How many integers from 1 to {comma(upper)} inclusive are divisible by {a} or by {b} (or by "
        f"both), but are not divisible by {c}?"
    )
    return question, number(count)


def _no_adjacent_vowels(word: str) -> int:
    counts: dict[str, int] = {}
    for letter in word:
        counts[letter] = counts.get(letter, 0) + 1
    letters = sorted(counts)

    def walk(remaining: int, last_vowel: bool) -> int:
        if remaining == 0:
            return 1
        total = 0
        for letter in letters:
            if not counts[letter]:
                continue
            vowel = letter in "AEIOU"
            if vowel and last_vowel:
                continue
            counts[letter] -= 1
            total += walk(remaining - 1, vowel)
            counts[letter] += 1
        return total

    return walk(len(word), False)


def m12(rng: LCG):
    word = rng.choice(["SEPARATE", "COMMITTEE", "TENNESSEE", "REFERENCE", "ELEVATED", "CASSETTE", "BALLOONS"])
    count = _no_adjacent_vowels(word)
    if len(word) <= 8:
        brute = {p for p in itertools.permutations(word)
                 if not any(x in "AEIOU" and y in "AEIOU" for x, y in zip(p, p[1:]))}
        assert len(brute) == count
    if count == 0:
        raise Retry
    question = (
        f"How many distinct arrangements of all the letters of the word {word} have no two vowels "
        f"next to each other? (The vowels are A, E, I, O and U. Arrangements that look identical "
        f"count once.)"
    )
    return question, number(count)


def _paths(width, height, via, blocked) -> int:
    """Count monotone paths that visit `via` and avoid `blocked`, tracking a visited flag."""
    table = {(0, 0, (0, 0) == via): 1}
    for x in range(width + 1):
        for y in range(height + 1):
            for seen in (False, True):
                ways = table.get((x, y, seen), 0)
                if not ways:
                    continue
                for nx, ny in ((x + 1, y), (x, y + 1)):
                    if nx > width or ny > height or (nx, ny) == blocked:
                        continue
                    key = (nx, ny, seen or (nx, ny) == via)
                    table[key] = table.get(key, 0) + ways
    return table.get((width, height, True), 0)


def m13(rng: LCG):
    width, height = rng.randint(7, 10), rng.randint(6, 9)
    via = (rng.randint(2, width - 3), rng.randint(2, height - 3))
    blocked = (rng.randint(1, width - 1), rng.randint(1, height - 1))
    if blocked == via:
        raise Retry
    count = _paths(width, height, via, blocked)
    unrestricted = math.comb(via[0] + via[1], via[0]) * math.comb(width - via[0] + height - via[1], width - via[0])
    if count == unrestricted or count == 0:
        raise Retry                              # the blocked point must actually matter
    question = (
        f"A robot starts at the point (0, 0) on a grid and must reach the point ({width}, {height}). "
        f"Each move takes it exactly one unit to the right or exactly one unit up. Its path must "
        f"pass through the point ({via[0]}, {via[1]}) and must not pass through the point "
        f"({blocked[0]}, {blocked[1]}). How many different paths can the robot take?"
    )
    return question, number(count)


def m14(rng: LCG):
    base_a, base_b = rng.choice([(7, 13), (3, 17), (11, 19), (13, 7), (17, 3)])
    exp_a, exp_b = rng.randint(211, 989), rng.randint(211, 989)
    answer = (pow(base_a, exp_a, 1000) + pow(base_b, exp_b, 1000)) % 1000
    assert answer == (base_a ** exp_a + base_b ** exp_b) % 1000
    question = (
        f"What is the remainder when {base_a}^{exp_a} + {base_b}^{exp_b} is divided by 1000? "
        f"(Here ^ means exponentiation.)"
    )
    return question, number(answer)


def m15(rng: LCG):
    digit_sum = rng.randint(14, 23)
    banned = rng.randint(3, 8)
    count = sum(1 for n in range(1000, 10000)
                if sum(map(int, str(n))) == digit_sum and str(banned) not in str(n))
    question = (
        f"How many integers from 1000 to 9999 inclusive have digits that add up to exactly "
        f"{digit_sum} and do not contain the digit {banned} anywhere?"
    )
    return question, number(count)


def m16(rng: LCG):
    red, green, blue = rng.randint(3, 7), rng.randint(3, 7), rng.randint(3, 7)
    if len({red, green, blue}) < 2:
        raise Retry
    marbles = "R" * red + "G" * green + "B" * blue
    draws = list(itertools.combinations(range(len(marbles)), 4))
    good = sum(1 for draw in draws if {marbles[i] for i in draw} == {"R", "G", "B"})
    probability = Fraction(good, len(draws))
    closed = (math.comb(red, 2) * green * blue + red * math.comb(green, 2) * blue
              + red * green * math.comb(blue, 2))
    assert closed == good
    question = (
        f"A bag contains {red} red, {green} green and {blue} blue marbles. Four marbles are drawn at "
        f"random without replacement. The probability that the four marbles include at least one "
        f"marble of each of the three colors can be written as p/q, where p and q are positive "
        f"integers with no common factor greater than 1. What is p + q?"
    )
    return question, number(probability.numerator + probability.denominator)


# ----------------------------------------------------------------------------- tier 4

def m17(rng: LCG):
    start = rng.randint(90, 160)
    removed = rng.randint(20, 45)
    hours = 10
    count = start
    for _ in range(hours):
        grown = count * 3 // 2
        nxt = grown - removed
        if nxt <= count:
            raise Retry
        count = nxt
    question = (
        f"A lab culture starts with {start} bacteria. Every hour, exactly two things happen, in "
        f"this order: first the number of bacteria increases by 50% (if that is not a whole number, "
        f"it is rounded down to a whole number), and then exactly {removed} bacteria are removed for "
        f"testing. How many bacteria are in the culture after {hours} hours?"
    )
    return question, number(count)


def m18(rng: LCG):
    period_h, period_m = rng.choice([(7, 25), (5, 35), (9, 50), (6, 45), (11, 20)])
    start_h, start_m = rng.randint(6, 11), rng.choice([10, 20, 40, 50])
    nth = rng.randint(120, 400)
    period = period_h * 60 + period_m
    total = start_h * 60 + start_m + (nth - 1) * period
    day = (total // 1440) % 7 + 1
    hour, minute = (total % 1440) // 60, total % 60
    # Independent check: step reading by reading.
    d, h, m = 1, start_h, start_m
    for _ in range(nth - 1):
        m += period_m
        h += period_h + m // 60
        m %= 60
        d = (d - 1 + h // 24) % 7 + 1
        h %= 24
    assert (d, h, m) == (day, hour, minute)
    question = (
        f"A sensor takes a reading every {period_h} hours {period_m} minutes. The 1st reading is "
        f"taken on a Monday at {start_h:02d}:{start_m:02d} (24-hour clock). Consider the {nth}th "
        f"reading. Let d be the day of the week on which it is taken, with Monday = 1, Tuesday = 2, "
        f"and so on up to Sunday = 7, and let h and m be the hour (0 to 23) and minute (0 to 59) "
        f"shown on a 24-hour clock at that moment. What is 10000*d + 100*h + m?"
    )
    return question, number(10000 * day + 100 * hour + minute)


def m19(rng: LCG):
    n = rng.randint(150, 400)
    base = rng.choice([12, 18, 20, 24, 45, 48])
    factors: dict[int, int] = {}
    rest, p = base, 2
    while rest > 1:
        while rest % p == 0:
            factors[p] = factors.get(p, 0) + 1
            rest //= p
        p += 1

    def legendre(prime: int) -> int:
        total, power = 0, prime
        while power <= n:
            total += n // power
            power *= prime
        return total

    answer = min(legendre(prime) // exponent for prime, exponent in factors.items())
    value, zeros = math.factorial(n), 0
    while value % base == 0:
        value //= base
        zeros += 1
    assert zeros == answer
    question = (
        f"When the number {n}! (the factorial of {n}) is written in base {base}, how many zeros "
        f"does it end with?"
    )
    return question, number(answer)


def m20(rng: LCG):
    people = rng.randint(43, 90)
    step = rng.randint(3, 7)
    circle = list(range(1, people + 1))
    index = 0
    while len(circle) > 1:
        index = (index + step - 1) % len(circle)
        circle.pop(index)
    survivor = 0
    for size in range(2, people + 1):
        survivor = (survivor + step) % size
    assert circle[0] == survivor + 1
    question = (
        f"{people} people stand in a circle, numbered 1 to {people} clockwise. Counting starts at "
        f"person 1 and goes clockwise: person 1 says \"1\", the next person still in the circle says "
        f"\"2\", and so on. Whoever says \"{step}\" leaves the circle, and the count starts again at "
        f"\"1\" with the next person clockwise who is still in the circle. (So the first person to "
        f"leave is person {step}.) This continues until one person remains. What is the number of "
        f"the last person remaining?"
    )
    return question, number(circle[0])


PROBLEMS = [
    (m01, 1, "tiered pricing"), (m02, 1, "overtime pay"), (m03, 1, "piecewise rates"),
    (m04, 1, "scaling and units"), (m05, 1, "sequential percentages"),
    (m06, 2, "work backwards"), (m07, 2, "relative motion"), (m08, 2, "mixtures"),
    (m09, 2, "linear system"), (m10, 2, "work rates"),
    (m11, 3, "inclusion-exclusion"), (m12, 3, "constrained arrangements"), (m13, 3, "lattice paths"),
    (m14, 3, "modular arithmetic"), (m15, 3, "digit counting"),
    (m16, 4, "probability"), (m17, 4, "iterated process"), (m18, 4, "clock arithmetic"),
    (m19, 4, "factorial valuations"), (m20, 4, "elimination game"),
]


def build() -> list[dict]:
    rows = []
    for index, (maker, tier, topic) in enumerate(PROBLEMS, start=1):
        rng = LCG(BASE_SEED * 1000 + index)
        for _ in range(100000):
            try:
                question, answer = maker(rng)
                break
            except Retry:
                continue
        else:
            raise RuntimeError(f"m{index:02d}: no clean instance found")
        rows.append({"key": f"m{index:02d}", "tier": tier, "topic": topic,
                     "question": question, "answer": answer})
    return rows


def render(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify the shipped file instead of writing it")
    args = parser.parse_args(argv)
    text = render(build())
    if args.check:
        if OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} differs from the builder output", file=sys.stderr)
            return 1
        print(f"{OUT.name}: up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({text.count(chr(10))} problems)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
