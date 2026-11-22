"""Deterministic builder for sixcat/data/v2_code.jsonl (challenge-v2 Code).

Twenty original function-level problems, written for this benchmark (no
HumanEval, LeetCode or other dataset text is copied). Each row has the same
shape as HumanEval so the existing guarded runner can execute it:

    task_id, entry_point, prompt, canonical_solution, test

For every problem this script:

  1. runs the reference solution against an independent brute-force / second
     implementation on a few hundred seeded random inputs,
  2. computes expected outputs for the hand-written and larger "performance"
     cases with the reference,
  3. emits a `check(candidate)` test made of literal asserts.

    python tools/build_v2_code.py            # rewrite the data file
    python tools/build_v2_code.py --check    # fail if the file differs
"""
from __future__ import annotations

import argparse
import doctest
import itertools
import json
import sys
import textwrap
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "sixcat" / "data" / "v2_code.jsonl"

PRELUDE = '''\
def _rng(seed):
    state = [seed]
    def nxt(bound):
        state[0] = (state[0] * 6364136223846793005 + 1442695040888963407) % 18446744073709551616
        return (state[0] >> 33) % bound
    return nxt


def _n(value):
    if isinstance(value, (list, tuple)):
        return [_n(item) for item in value]
    return value


def _digest(value):
    import hashlib
    return hashlib.sha256(repr(_n(value)).encode("utf-8")).hexdigest()[:20]
'''

_PRELUDE_NS: dict = {}
exec(PRELUDE, _PRELUDE_NS)
_rng, _n, _digest = _PRELUDE_NS["_rng"], _PRELUDE_NS["_n"], _PRELUDE_NS["_digest"]

PROBLEMS: list[dict] = []


def problem(**spec) -> None:
    spec["prompt"] = textwrap.dedent(spec["prompt"]).lstrip("\n")
    spec["solution"] = textwrap.dedent(spec["solution"]).lstrip("\n")
    spec.setdefault("perf", [])
    spec.setdefault("big", [])
    spec.setdefault("raises", [])
    PROBLEMS.append(spec)


# ----------------------------------------------------------------------------- 01

def _brute_evaluate(expr):
    class Swapped:
        def __init__(self, value):
            self.value = value

        def __add__(self, other):          # written '*' in the source expression
            return Swapped(self.value * other.value)

        def __mul__(self, other):          # written '+' in the source expression
            return Swapped(self.value + other.value)

    out, i = [], 0
    while i < len(expr):
        ch = expr[i]
        if ch.isdigit():
            j = i
            while j < len(expr) and expr[j].isdigit():
                j += 1
            out.append(f"S({int(expr[i:j])})")
            i = j
            continue
        out.append({"+": "*", "*": "+"}.get(ch, ch))
        i += 1
    return eval("".join(out), {"S": Swapped}).value


def _fuzz_evaluate(nxt):
    def build(depth):
        if depth == 0 or nxt(4) == 0:
            return str(nxt(12))
        parts = [build(depth - 1) for _ in range(2 + nxt(3))]
        text = parts[0]
        for part in parts[1:]:
            text += [" + ", "*", " * ", "+"][nxt(4)] + part
        return f"({text})" if nxt(2) else text
    return (build(3),)


problem(
    task_id="sixcat-v2/01", entry="evaluate",
    prompt='''
    def evaluate(expr: str) -> int:
        """Evaluate an arithmetic expression written in a language where addition
        binds TIGHTER than multiplication (the reverse of normal arithmetic).

        `expr` contains non-negative decimal integers, the operators '+' and '*',
        parentheses, and spaces (which are ignored). Parentheses group as usual.
        Both operators are left-associative. The expression is always well-formed.

        >>> evaluate("2 * 3 + 4")
        14
        >>> evaluate("2 + 3 * 4")
        20
        >>> evaluate("(2 * 3) + 4")
        10
        >>> evaluate("1 + 2 * 3 + 4 * 5")
        105
        """
    ''',
    solution='''
    def evaluate(expr: str) -> int:
        tokens = []
        i = 0
        while i < len(expr):
            ch = expr[i]
            if ch == " ":
                i += 1
            elif ch.isdigit():
                j = i
                while j < len(expr) and expr[j].isdigit():
                    j += 1
                tokens.append(int(expr[i:j]))
                i = j
            else:
                tokens.append(ch)
                i += 1
        pos = [0]

        def atom():
            token = tokens[pos[0]]
            pos[0] += 1
            if token == "(":
                value = product()
                pos[0] += 1
                return value
            return token

        def total():
            value = atom()
            while pos[0] < len(tokens) and tokens[pos[0]] == "+":
                pos[0] += 1
                value += atom()
            return value

        def product():
            value = total()
            while pos[0] < len(tokens) and tokens[pos[0]] == "*":
                pos[0] += 1
                value *= total()
            return value

        return product()
    ''',
    cases=[("2 * 3 + 4",), ("2 + 3 * 4",), ("(2 * 3) + 4",), ("1 + 2 * 3 + 4 * 5",), ("7",), ("  12  ",),
           ("((5))",), ("0 * 9 + 9",), ("10+20*30+40",), ("2*(3*4)+5*6",), ("(1+1)*(2+2)*(3+3)",),
           ("100 * 100 + 100 * 100",), ("3 + (4 * 5) + 6 * 2",), ("1*2*3*4+5",)],
    brute=_brute_evaluate, fuzz=_fuzz_evaluate,
)

# ----------------------------------------------------------------------------- 02


def _brute_longest_balanced(s):
    best = 0
    for i in range(len(s)):
        a = b = c = 0
        for j in range(i, len(s)):
            ch = s[j]
            a += ch == "a"
            b += ch == "b"
            c += ch == "c"
            if a == b == c:
                best = max(best, j - i + 1)
    return best


problem(
    task_id="sixcat-v2/02", entry="longest_balanced",
    prompt='''
    def longest_balanced(s: str) -> int:
        """Return the length of the longest contiguous substring of `s` that
        contains equally many 'a', 'b' and 'c' characters.

        `s` consists only of the characters 'a', 'b' and 'c' and may be empty.
        The empty substring is balanced, so the answer is at least 0.
        `s` can be up to 200,000 characters long, so a quadratic scan is too slow.

        >>> longest_balanced("abc")
        3
        >>> longest_balanced("aabbc")
        0
        >>> longest_balanced("aabcbcc")
        6
        >>> longest_balanced("ccabacb")
        6
        """
    ''',
    solution='''
    def longest_balanced(s: str) -> int:
        first = {(0, 0): -1}
        ab = ac = 0
        best = 0
        for index, ch in enumerate(s):
            if ch == "a":
                ab += 1
                ac += 1
            elif ch == "b":
                ab -= 1
            else:
                ac -= 1
            key = (ab, ac)
            if key in first:
                best = max(best, index - first[key])
            else:
                first[key] = index
        return best
    ''',
    cases=[("abc",), ("aabbc",), ("aabcbcc",), ("ccabacb",), ("",), ("a",), ("cba" * 5,), ("aaabbbccc",),
           ("abcabcab",), ("bbbbbbb",), ("acbbca" + "a" * 4,), ("cabcabcabx".replace("x", "c"),)],
    brute=_brute_longest_balanced,
    fuzz=lambda nxt: ("".join("abc"[nxt(3)] for _ in range(nxt(30))),),
    perf=['''
    nxt = _rng(202)
    args = ("".join("abc"[nxt(3)] for _ in range(200000)),)
    ''', '''
    args = ("a" * 70000 + "b" * 70000 + "c" * 60000,)
    '''],
)

# ----------------------------------------------------------------------------- 03


def _brute_lcs3(a, b, c):
    def is_sub(x, y):
        it = iter(y)
        return all(ch in it for ch in x)
    short = min((a, b, c), key=len)
    for size in range(len(short), -1, -1):
        for combo in itertools.combinations(range(len(short)), size):
            cand = "".join(short[i] for i in combo)
            if is_sub(cand, a) and is_sub(cand, b) and is_sub(cand, c):
                return size
    return 0


problem(
    task_id="sixcat-v2/03", entry="lcs3",
    prompt='''
    def lcs3(a: str, b: str, c: str) -> int:
        """Return the length of the longest string that is a subsequence of all
        three of `a`, `b` and `c`.

        A subsequence keeps characters in their original order but need not be
        contiguous. Each input is at most 60 characters long and may be empty.

        >>> lcs3("abcde", "ace", "aXcYe")
        3
        >>> lcs3("abc", "def", "ghi")
        0
        >>> lcs3("xyzzy", "zyxzy", "yzyzx")
        3
        """
    ''',
    solution='''
    def lcs3(a: str, b: str, c: str) -> int:
        la, lb, lc = len(a), len(b), len(c)
        prev = [[0] * (lc + 1) for _ in range(lb + 1)]
        for i in range(1, la + 1):
            cur = [[0] * (lc + 1) for _ in range(lb + 1)]
            ai = a[i - 1]
            for j in range(1, lb + 1):
                row, up, left = cur[j], prev[j], cur[j - 1]
                diag = prev[j - 1]
                match_ab = ai == b[j - 1]
                for k in range(1, lc + 1):
                    if match_ab and ai == c[k - 1]:
                        row[k] = diag[k - 1] + 1
                    else:
                        best = up[k]
                        if left[k] > best:
                            best = left[k]
                        if row[k - 1] > best:
                            best = row[k - 1]
                        row[k] = best
            prev = cur
        return prev[lb][lc]
    ''',
    cases=[("abcde", "ace", "aXcYe"), ("abc", "def", "ghi"), ("xyzzy", "zyxzy", "yzyzx"), ("", "a", "a"),
           ("aaaa", "aa", "aaa"), ("abcbdab", "bdcaba", "badacb"), ("same", "same", "same"),
           ("abcdefgh", "hgfedcba", "aabbccdd"), ("mississippi", "missouri", "misty isle")],
    big=[("the quick brown fox jumps over the lazy dog", "pack my box with five dozen liquor jugs",
          "how vexingly quick daft zebras jump")],
    brute=_brute_lcs3,
    fuzz=lambda nxt: tuple("".join("abc"[nxt(3)] for _ in range(nxt(9))) for _ in range(3)),
    perf=['''
    nxt = _rng(303)
    args = tuple("".join("abcd"[nxt(4)] for _ in range(60)) for _ in range(3))
    '''],
)

# ----------------------------------------------------------------------------- 04


def _brute_coupons(n, edges, src, dst, k):
    inf = float("inf")
    dist = [[inf] * n for _ in range(k + 1)]
    dist[0][src] = 0
    for _ in range(n * (k + 1) + 1):
        changed = False
        for used in range(k + 1):
            for u, v, w in edges:
                base = dist[used][u]
                if base == inf:
                    continue
                if base + w < dist[used][v]:
                    dist[used][v] = base + w
                    changed = True
                if used < k and base < dist[used + 1][v]:
                    dist[used + 1][v] = base
                    changed = True
        if not changed:
            break
    best = min(dist[used][dst] for used in range(k + 1))
    return -1 if best == inf else best


def _fuzz_coupons(nxt):
    n = 2 + nxt(6)
    edges = [(nxt(n), nxt(n), nxt(20)) for _ in range(nxt(14))]
    return (n, edges, nxt(n), nxt(n), nxt(3))


problem(
    task_id="sixcat-v2/04", entry="cheapest_route",
    prompt='''
    def cheapest_route(n: int, edges: list, src: int, dst: int, k: int) -> int:
        """Return the minimum total toll to travel from city `src` to city `dst`.

        Cities are numbered 0..n-1. `edges` is a list of one-way roads
        (u, v, toll) with integer toll >= 0; there may be several roads between
        the same pair of cities and roads from a city to itself. You hold `k`
        coupons (k >= 0); each coupon makes one road you drive along free, and
        you may use at most one coupon per road. Unused coupons are fine.

        Return -1 if `dst` cannot be reached from `src`. If src == dst the
        answer is 0. n is at most 2,000 and there are at most 10,000 roads.

        >>> cheapest_route(3, [(0, 1, 5), (1, 2, 7)], 0, 2, 0)
        12
        >>> cheapest_route(3, [(0, 1, 5), (1, 2, 7)], 0, 2, 1)
        5
        >>> cheapest_route(3, [(0, 1, 5), (1, 2, 7), (0, 2, 20)], 0, 2, 1)
        0
        >>> cheapest_route(2, [(1, 0, 3)], 0, 1, 5)
        -1
        """
    ''',
    solution='''
    import heapq


    def cheapest_route(n: int, edges: list, src: int, dst: int, k: int) -> int:
        graph = [[] for _ in range(n)]
        for u, v, toll in edges:
            graph[u].append((v, toll))
        inf = float("inf")
        best = [[inf] * (k + 1) for _ in range(n)]
        best[src][0] = 0
        heap = [(0, src, 0)]
        while heap:
            cost, node, used = heapq.heappop(heap)
            if cost > best[node][used]:
                continue
            if node == dst:
                return cost
            for nxt_node, toll in graph[node]:
                if cost + toll < best[nxt_node][used]:
                    best[nxt_node][used] = cost + toll
                    heapq.heappush(heap, (cost + toll, nxt_node, used))
                if used < k and cost < best[nxt_node][used + 1]:
                    best[nxt_node][used + 1] = cost
                    heapq.heappush(heap, (cost, nxt_node, used + 1))
        return -1
    ''',
    cases=[(3, [(0, 1, 5), (1, 2, 7)], 0, 2, 0), (3, [(0, 1, 5), (1, 2, 7)], 0, 2, 1),
           (3, [(0, 1, 5), (1, 2, 7), (0, 2, 20)], 0, 2, 1), (2, [(1, 0, 3)], 0, 1, 5), (1, [], 0, 0, 0),
           (4, [(0, 1, 1), (1, 2, 1), (2, 3, 1), (0, 3, 10)], 0, 3, 0),
           (4, [(0, 1, 9), (1, 2, 9), (2, 3, 9), (0, 3, 30)], 0, 3, 2),
           (5, [(0, 1, 4), (0, 1, 2), (1, 1, 0), (1, 4, 8), (0, 4, 11), (4, 0, 1)], 0, 4, 1),
           (3, [(0, 1, 0), (1, 2, 0)], 0, 2, 3), (4, [(0, 1, 2), (2, 3, 2)], 0, 3, 4)],
    brute=_brute_coupons, fuzz=_fuzz_coupons,
    perf=['''
    nxt = _rng(404)
    n = 2000
    edges = [(i, i + 1, 1 + nxt(50)) for i in range(n - 1)]
    edges += [(nxt(n), nxt(n), 1 + nxt(1000)) for _ in range(8000)]
    args = (n, edges, 0, n - 1, 3)
    '''],
)

# ----------------------------------------------------------------------------- 05


def _brute_islands(rows, cols, cells):
    land, out = set(), []
    for cell in cells:
        land.add(tuple(cell))
        seen, count = set(), 0
        for start in land:
            if start in seen:
                continue
            count += 1
            stack = [start]
            seen.add(start)
            while stack:
                r, c = stack.pop()
                for nb in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                    if nb in land and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        out.append(count)
    return out


def _fuzz_islands(nxt):
    rows, cols = 1 + nxt(5), 1 + nxt(5)
    return (rows, cols, [(nxt(rows), nxt(cols)) for _ in range(nxt(18))])


problem(
    task_id="sixcat-v2/05", entry="islands_after_each",
    prompt='''
    def islands_after_each(rows: int, cols: int, cells: list) -> list:
        """A `rows` x `cols` grid starts as all water. The (row, col) positions in
        `cells` are turned into land one at a time, in order. Return a list with
        the number of islands after each step.

        An island is a maximal group of land cells connected horizontally or
        vertically (not diagonally). A position may appear more than once in
        `cells`; turning land into land changes nothing, but that step still
        gets an entry in the result. There can be up to 100,000 steps, so
        recounting the whole grid after every step is too slow.

        >>> islands_after_each(3, 3, [(0, 0), (0, 1), (1, 2), (2, 1), (1, 1)])
        [1, 1, 2, 3, 1]
        >>> islands_after_each(1, 4, [(0, 0), (0, 2), (0, 0), (0, 1)])
        [1, 2, 2, 1]
        """
    ''',
    solution='''
    def islands_after_each(rows: int, cols: int, cells: list) -> list:
        parent = {}

        def find(x):
            root = x
            while parent[root] != root:
                root = parent[root]
            while parent[x] != root:
                parent[x], x = root, parent[x]
            return root

        count = 0
        result = []
        for r, c in cells:
            key = r * cols + c
            if key not in parent:
                parent[key] = key
                count += 1
                for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                    if 0 <= nr < rows and 0 <= nc < cols:
                        other = nr * cols + nc
                        if other in parent:
                            a, b = find(key), find(other)
                            if a != b:
                                parent[a] = b
                                count -= 1
            result.append(count)
        return result
    ''',
    cases=[(3, 3, [(0, 0), (0, 1), (1, 2), (2, 1), (1, 1)]), (1, 4, [(0, 0), (0, 2), (0, 0), (0, 1)]),
           (2, 2, []), (1, 1, [(0, 0), (0, 0)]), (3, 3, [(1, 1), (0, 0), (2, 2), (0, 2), (2, 0)]),
           (2, 5, [(0, 0), (1, 4), (0, 4), (0, 2), (0, 1), (0, 3)]),
           (4, 4, [(r, c) for r in range(4) for c in range(4) if (r + c) % 2 == 0] + [(1, 0), (2, 3)])],
    brute=_brute_islands, fuzz=_fuzz_islands,
    perf=['''
    nxt = _rng(505)
    args = (300, 300, [(nxt(300), nxt(300)) for _ in range(100000)])
    '''],
)

# ----------------------------------------------------------------------------- 06


def _brute_sjf(tasks):
    remaining = set(range(len(tasks)))
    now, order = 0, []
    while remaining:
        ready = [i for i in remaining if tasks[i][0] <= now]
        if not ready:
            now = min(tasks[i][0] for i in remaining)
            continue
        pick = min(ready, key=lambda i: (tasks[i][1], i))
        order.append(pick)
        remaining.discard(pick)
        now += tasks[pick][1]
    return order


problem(
    task_id="sixcat-v2/06", entry="run_order",
    prompt='''
    def run_order(tasks: list) -> list:
        """A single machine runs tasks one at a time and never interrupts a task.
        `tasks[i] = (release, duration)`: task i may start at time `release` or
        later and then runs for `duration` time units (both integers,
        release >= 0, duration >= 1).

        Whenever the machine is free it immediately starts, among the tasks
        already released (release <= current time) and not yet run, the one with
        the smallest duration; ties are broken by the smaller index. If no task
        has been released yet, the machine waits until the next release time.
        The machine is first free at time 0.

        Return the task indices in the order they run. There can be up to
        100,000 tasks.

        >>> run_order([(0, 5), (1, 2), (2, 1)])
        [0, 2, 1]
        >>> run_order([(3, 2), (3, 2), (0, 10)])
        [2, 0, 1]
        >>> run_order([(5, 1), (9, 1)])
        [0, 1]
        """
    ''',
    solution='''
    import heapq


    def run_order(tasks: list) -> list:
        by_release = sorted(range(len(tasks)), key=lambda i: (tasks[i][0], i))
        heap, order = [], []
        now, pointer, total = 0, 0, len(tasks)
        while len(order) < total:
            while pointer < total and tasks[by_release[pointer]][0] <= now:
                index = by_release[pointer]
                heapq.heappush(heap, (tasks[index][1], index))
                pointer += 1
            if not heap:
                now = tasks[by_release[pointer]][0]
                continue
            duration, index = heapq.heappop(heap)
            order.append(index)
            now += duration
        return order
    ''',
    cases=[([(0, 5), (1, 2), (2, 1)],), ([(3, 2), (3, 2), (0, 10)],), ([(5, 1), (9, 1)],), ([],),
           ([(0, 1)],), ([(0, 3), (0, 3), (0, 3)],), ([(10, 4), (0, 2), (2, 9), (3, 1), (11, 1)],),
           ([(4, 1), (4, 1), (0, 4), (1, 3), (100, 2), (8, 1)],), ([(7, 7), (0, 7), (7, 6), (14, 1)],)],
    brute=_brute_sjf,
    fuzz=lambda nxt: ([(nxt(15), 1 + nxt(6)) for _ in range(nxt(10))],),
    perf=['''
    nxt = _rng(606)
    args = ([(nxt(400000), 1 + nxt(9)) for _ in range(100000)],)
    '''],
)

# ----------------------------------------------------------------------------- 07


def _brute_subtract(a, b):
    points = set()
    for s, e in a:
        points.update(range(s, e))
    for s, e in b:
        points.difference_update(range(s, e))
    out = []
    for x in sorted(points):
        if out and out[-1][1] == x:
            out[-1][1] = x + 1
        else:
            out.append([x, x + 1])
    return out


def _fuzz_subtract(nxt):
    def group():
        return [(nxt(24) - 4, nxt(24) - 4) for _ in range(nxt(6))]
    return (group(), group())


problem(
    task_id="sixcat-v2/07", entry="subtract_intervals",
    prompt='''
    def subtract_intervals(a: list, b: list) -> list:
        """`a` and `b` are lists of integer intervals (start, end) that are
        half-open: an interval covers every real x with start <= x < end.
        Intervals within a list may be unsorted, may overlap and may touch.
        An interval with start >= end is empty and must be ignored.

        Return the set of points covered by at least one interval of `a` and by
        no interval of `b`, as a list of (start, end) half-open intervals that
        is sorted by start, pairwise disjoint, and maximal (no two result
        intervals overlap or touch, and none is empty).

        >>> subtract_intervals([(0, 10)], [(3, 5)])
        [(0, 3), (5, 10)]
        >>> subtract_intervals([(0, 4), (4, 8)], [(8, 9)])
        [(0, 8)]
        >>> subtract_intervals([(5, 9), (1, 3)], [(0, 2), (6, 7), (8, 20)])
        [(2, 3), (5, 6), (7, 8)]
        >>> subtract_intervals([(1, 2)], [(0, 5)])
        []
        """
    ''',
    solution='''
    def subtract_intervals(a: list, b: list) -> list:
        def merge(items):
            merged = []
            for start, end in sorted((s, e) for s, e in items if s < e):
                if merged and start <= merged[-1][1]:
                    if end > merged[-1][1]:
                        merged[-1][1] = end
                else:
                    merged.append([start, end])
            return merged

        keep, cut = merge(a), merge(b)
        result = []
        j = 0
        for start, end in keep:
            cursor = start
            while j < len(cut) and cut[j][1] <= cursor:
                j += 1
            i = j
            while i < len(cut) and cut[i][0] < end:
                if cut[i][0] > cursor:
                    result.append((cursor, cut[i][0]))
                if cut[i][1] > cursor:
                    cursor = cut[i][1]
                i += 1
            if cursor < end:
                result.append((cursor, end))
        return result
    ''',
    cases=[([(0, 10)], [(3, 5)]), ([(0, 4), (4, 8)], [(8, 9)]), ([(5, 9), (1, 3)], [(0, 2), (6, 7), (8, 20)]),
           ([(1, 2)], [(0, 5)]), ([], [(0, 1)]), ([(0, 5)], []), ([(3, 3), (7, 2)], [(0, 9)]),
           ([(0, 100)], [(10, 20), (15, 30), (30, 31), (99, 100), (-5, 1)]),
           ([(-10, -5), (-7, 0), (2, 4)], [(-6, -6), (-1, 3)]), ([(0, 2), (2, 4), (6, 8)], [(4, 6)]),
           ([(0, 10), (20, 30)], [(5, 25)]), ([(0, 3)], [(0, 3)])],
    brute=_brute_subtract, fuzz=_fuzz_subtract,
    perf=['''
    nxt = _rng(707)
    a = [(s, s + 1 + nxt(40)) for s in (nxt(4000000) for _ in range(60000))]
    b = [(s, s + 1 + nxt(25)) for s in (nxt(4000000) for _ in range(60000))]
    args = (a, b)
    '''],
)

# ----------------------------------------------------------------------------- 08


def _brute_digit(p, q, n):
    remainder, digit = p % q, 0
    for _ in range(n):
        remainder *= 10
        digit, remainder = divmod(remainder, q)
    return digit


problem(
    task_id="sixcat-v2/08", entry="nth_decimal_digit",
    prompt='''
    def nth_decimal_digit(p: int, q: int, n: int) -> int:
        """Return the n-th digit after the decimal point in the decimal expansion
        of the fraction p/q, where 1 <= p < q and n >= 1 (n = 1 is the first
        digit after the point). Terminating expansions continue with zeros.

        q can be as large as 10**9 and n as large as 10**18, so the digits
        cannot be generated one by one.

        >>> nth_decimal_digit(1, 7, 1)
        1
        >>> nth_decimal_digit(1, 7, 6)
        7
        >>> nth_decimal_digit(1, 4, 5)
        0
        >>> nth_decimal_digit(22, 23, 100)
        0
        """
    ''',
    solution='''
    def nth_decimal_digit(p: int, q: int, n: int) -> int:
        remainder = (p % q) * pow(10, n - 1, q) % q
        return remainder * 10 // q
    ''',
    cases=[(1, 7, 1), (1, 7, 6), (1, 4, 5), (22, 23, 100), (1, 3, 999), (1, 2, 1), (1, 2, 2), (5, 8, 3),
           (1, 97, 96), (1, 97, 97), (355, 452, 12), (1, 1000000007, 1), (999999999, 1000000000, 9),
           (999999999, 1000000000, 10)],
    big=[(123456789, 987654321, 10 ** 18), (1, 7, 10 ** 18), (314159, 999983, 123456789012345678),
         (2, 3, 10 ** 17 + 3)],
    brute=_brute_digit,
    fuzz=lambda nxt: (lambda q: (1 + nxt(q - 1), q, 1 + nxt(60)))(2 + nxt(500)),
)

# ----------------------------------------------------------------------------- 09


def _brute_coprime(n):
    from math import gcd
    return sum(1 for b in range(2, n + 1) for a in range(1, b) if gcd(a, b) == 1)


problem(
    task_id="sixcat-v2/09", entry="count_coprime_pairs",
    prompt='''
    def count_coprime_pairs(n: int) -> int:
        """Return how many pairs of integers (a, b) with 1 <= a < b <= n have
        greatest common divisor 1.

        n is between 1 and 300,000, so checking every pair is far too slow.

        >>> count_coprime_pairs(1)
        0
        >>> count_coprime_pairs(2)
        1
        >>> count_coprime_pairs(5)
        9
        >>> count_coprime_pairs(10)
        31
        """
    ''',
    solution='''
    def count_coprime_pairs(n: int) -> int:
        phi = list(range(n + 1))
        for i in range(2, n + 1):
            if phi[i] == i:
                for multiple in range(i, n + 1, i):
                    phi[multiple] -= phi[multiple] // i
        return sum(phi[2:])
    ''',
    cases=[(1,), (2,), (3,), (5,), (10,), (12,), (30,), (97,), (100,), (1000,)],
    big=[(4096,), (30030,)],
    brute=_brute_coprime,
    fuzz=lambda nxt: (1 + nxt(70),),
    perf=['''
    args = (300000,)
    ''', '''
    args = (299993,)
    '''],
)

# ----------------------------------------------------------------------------- 10

problem(
    task_id="sixcat-v2/10", entry="min_xor_pair",
    prompt='''
    def min_xor_pair(nums: list) -> int:
        """Return the smallest value of nums[i] XOR nums[j] over all pairs of
        different positions i < j.

        `nums` holds at least two non-negative integers below 2**40 (values may
        repeat) and can contain up to 200,000 of them, so trying every pair is
        too slow.

        >>> min_xor_pair([1, 2, 3])
        1
        >>> min_xor_pair([8, 1, 6])
        7
        >>> min_xor_pair([5, 9, 5])
        0
        >>> min_xor_pair([0, 16, 21, 28])
        5
        """
    ''',
    solution='''
    def min_xor_pair(nums: list) -> int:
        ordered = sorted(nums)
        return min(x ^ y for x, y in zip(ordered, ordered[1:]))
    ''',
    cases=[([1, 2, 3],), ([8, 1, 6],), ([5, 9, 5],), ([0, 16, 21, 28],), ([7, 0],), ([2 ** 40 - 1, 0],),
           ([1024, 513, 255, 256],), ([12, 34, 56, 78, 90, 21, 43, 65, 87, 9],), ([3, 10, 5, 25, 2, 8],),
           ([1 << i for i in range(20)],)],
    brute=lambda nums: min(nums[i] ^ nums[j] for i in range(len(nums)) for j in range(i + 1, len(nums))),
    fuzz=lambda nxt: ([nxt(1 << (3 + nxt(10))) for _ in range(2 + nxt(9))],),
    perf=['''
    nxt = _rng(1010)
    args = ([nxt(1 << 20) * (1 << 20) + nxt(1 << 20) for _ in range(200000)],)
    '''],
)

# ----------------------------------------------------------------------------- 11


def _brute_lfu(capacity, ops):
    store, clock, out = {}, 0, []
    for op in ops:
        clock += 1
        if op[0] == "get":
            key = op[1]
            if key in store:
                value, freq, _ = store[key]
                store[key] = (value, freq + 1, clock)
                out.append(value)
            else:
                out.append(-1)
        else:
            _, key, value = op
            if capacity == 0:
                continue
            if key in store:
                store[key] = (value, store[key][1] + 1, clock)
                continue
            if len(store) == capacity:
                victim = min(store, key=lambda k: (store[k][1], store[k][2]))
                del store[victim]
            store[key] = (value, 1, clock)
    return out


def _fuzz_lfu(nxt):
    ops = []
    for _ in range(nxt(40)):
        if nxt(2):
            ops.append(("put", nxt(6), nxt(100)))
        else:
            ops.append(("get", nxt(6)))
    return (nxt(4), ops)


problem(
    task_id="sixcat-v2/11", entry="lfu_trace",
    prompt='''
    def lfu_trace(capacity: int, ops: list) -> list:
        """Simulate a least-frequently-used cache holding at most `capacity`
        keys (capacity >= 0) and return the results of all "get" operations,
        in order.

        Each element of `ops` is ("get", key) or ("put", key, value); keys and
        values are non-negative integers.

        * get: if the key is present, the result is its value and the key's use
          count increases by 1; otherwise the result is -1.
        * put, key present: the value is replaced and the use count increases by 1.
        * put, key absent: if capacity is 0 nothing happens. Otherwise, if the
          cache is full, first evict the key with the smallest use count; among
          keys tied for the smallest count, evict the one whose most recent use
          (a successful get, or any put of that key) is oldest. Then insert the
          key with use count 1.

        >>> lfu_trace(2, [("put", 1, 10), ("put", 2, 20), ("get", 1), ("put", 3, 30), ("get", 2), ("get", 3)])
        [10, -1, 30]
        >>> lfu_trace(0, [("put", 1, 1), ("get", 1)])
        [-1]
        >>> lfu_trace(1, [("put", 5, 1), ("put", 5, 2), ("get", 5), ("put", 6, 3), ("get", 5), ("get", 6)])
        [2, -1, 3]
        """
    ''',
    solution='''
    from collections import OrderedDict


    def lfu_trace(capacity: int, ops: list) -> list:
        values, counts, buckets = {}, {}, {}
        lowest = [0]
        out = []

        def touch(key):
            count = counts[key]
            del buckets[count][key]
            if not buckets[count]:
                del buckets[count]
                if lowest[0] == count:
                    lowest[0] = count + 1
            counts[key] = count + 1
            buckets.setdefault(count + 1, OrderedDict())[key] = None

        for op in ops:
            if op[0] == "get":
                key = op[1]
                if key in values:
                    out.append(values[key])
                    touch(key)
                else:
                    out.append(-1)
                continue
            key, value = op[1], op[2]
            if capacity == 0:
                continue
            if key in values:
                values[key] = value
                touch(key)
                continue
            if len(values) == capacity:
                victim, _ = buckets[lowest[0]].popitem(last=False)
                if not buckets[lowest[0]]:
                    del buckets[lowest[0]]
                del values[victim]
                del counts[victim]
            values[key] = value
            counts[key] = 1
            buckets.setdefault(1, OrderedDict())[key] = None
            lowest[0] = 1
        return out
    ''',
    cases=[(2, [("put", 1, 10), ("put", 2, 20), ("get", 1), ("put", 3, 30), ("get", 2), ("get", 3)]),
           (0, [("put", 1, 1), ("get", 1)]),
           (1, [("put", 5, 1), ("put", 5, 2), ("get", 5), ("put", 6, 3), ("get", 5), ("get", 6)]),
           (2, [("get", 9)]), (3, []),
           (2, [("put", 1, 1), ("put", 2, 2), ("get", 2), ("get", 1), ("put", 3, 3), ("get", 1), ("get", 2), ("get", 3)]),
           (3, [("put", 1, 1), ("put", 2, 2), ("put", 3, 3), ("put", 2, 22), ("get", 1), ("put", 4, 4),
                ("get", 3), ("get", 4), ("get", 2), ("put", 5, 5), ("get", 1), ("get", 4), ("get", 5)]),
           (2, [("put", 3, 1), ("put", 2, 1), ("put", 2, 2), ("put", 4, 4), ("get", 2), ("get", 3), ("get", 4),
                ("put", 5, 5), ("get", 4), ("get", 2), ("get", 5)])],
    brute=_brute_lfu, fuzz=_fuzz_lfu,
    perf=['''
    nxt = _rng(1111)
    ops = []
    for _ in range(60000):
        if nxt(3):
            ops.append(("get", nxt(600)))
        else:
            ops.append(("put", nxt(600), nxt(1000)))
    args = (200, ops)
    '''],
)

# ----------------------------------------------------------------------------- 12


def _second_justify(words, width):
    lines, i = [], 0
    while i < len(words):
        j, length = i, 0
        while j < len(words) and length + len(words[j]) + (j - i) <= width:
            length += len(words[j])
            j += 1
        row = words[i:j]
        if j == len(words) or len(row) == 1:
            lines.append(" ".join(row).ljust(width))
        else:
            gaps = len(row) - 1
            base, extra = divmod(width - length, gaps)
            pieces = []
            for index, word in enumerate(row[:-1]):
                pieces.append(word + " " * (base + (1 if index < extra else 0)))
            lines.append("".join(pieces) + row[-1])
        i = j
    return lines


def _fuzz_justify(nxt):
    width = 4 + nxt(14)
    words = ["".join("abcdefg"[nxt(7)] for _ in range(1 + nxt(min(width, 7)))) for _ in range(1 + nxt(12))]
    return (words, width)


problem(
    task_id="sixcat-v2/12", entry="justify",
    prompt='''
    def justify(words: list, width: int) -> list:
        """Format `words` into lines of exactly `width` characters, fully
        justified, and return the list of lines.

        Rules:
        * Pack words greedily: each line takes as many of the next words as fit
          when consecutive words are separated by at least one space.
        * Every line except the last, if it holds two or more words, is padded
          with extra spaces between words so it is exactly `width` long. Spaces
          are spread as evenly as possible; when they do not divide evenly, the
          gaps further to the left get one more space than the gaps to the right.
        * A line holding a single word, and the last line, are left-justified:
          single spaces between words, then trailing spaces up to `width`.

        `words` is non-empty; every word is non-empty, has no spaces and is at
        most `width` characters long.

        >>> justify(["This", "is", "an", "example", "of", "text", "justification."], 16)
        ['This    is    an', 'example  of text', 'justification.  ']
        >>> justify(["a", "b", "c", "d"], 3)
        ['a b', 'c d']
        >>> justify(["longword", "x"], 8)
        ['longword', 'x       ']
        """
    ''',
    solution='''
    def justify(words: list, width: int) -> list:
        lines = []
        row, letters = [], 0
        for word in words:
            if row and letters + len(row) + len(word) > width:
                lines.append((row, letters))
                row, letters = [], 0
            row.append(word)
            letters += len(word)
        result = []
        for line_words, line_letters in lines:
            if len(line_words) == 1:
                result.append(line_words[0] + " " * (width - line_letters))
                continue
            gaps = len(line_words) - 1
            base, extra = divmod(width - line_letters, gaps)
            text = ""
            for index, word in enumerate(line_words):
                text += word
                if index < gaps:
                    text += " " * (base + (1 if index < extra else 0))
            result.append(text)
        last = " ".join(row)
        result.append(last + " " * (width - len(last)))
        return result
    ''',
    cases=[(["This", "is", "an", "example", "of", "text", "justification."], 16), (["a", "b", "c", "d"], 3),
           (["longword", "x"], 8), (["solo"], 10), (["a"], 1),
           (["What", "must", "be", "acknowledgment", "shall", "be"], 16),
           (["Science", "is", "what", "we", "understand", "well", "enough", "to", "explain", "to", "a",
             "computer.", "Art", "is", "everything", "else", "we", "do"], 20),
           (["aa", "bb", "cc", "dd", "ee", "ff", "gg"], 11), (["x", "y", "z"], 20),
           (["ab", "cd", "efgh", "i", "jklmno", "p", "q"], 6), (["one", "two", "three", "four"], 9)],
    brute=_second_justify, fuzz=_fuzz_justify,
)

# ----------------------------------------------------------------------------- 13


def _brute_expand(s):
    import re
    inner = re.compile(r"(\d+)\[([a-z]*)\]|<([a-z]*)>")
    while True:
        match = inner.search(s)
        if not match:
            return s
        if match.group(1) is not None:
            piece = match.group(2) * int(match.group(1))
        else:
            piece = match.group(3)[::-1]
        s = s[:match.start()] + piece + s[match.end():]


def _fuzz_expand(nxt):
    def build(depth):
        parts = []
        for _ in range(1 + nxt(3)):
            kind = nxt(4) if depth else 0
            if kind <= 1:
                parts.append("".join("abcde"[nxt(5)] for _ in range(nxt(3))))
            elif kind == 2:
                parts.append(f"{1 + nxt(3)}[{build(depth - 1)}]")
            else:
                parts.append(f"<{build(depth - 1)}>")
        return "".join(parts)
    return (build(3),)


problem(
    task_id="sixcat-v2/13", entry="expand",
    prompt='''
    def expand(s: str) -> str:
        """Expand a compressed string and return the result.

        `s` is built from three kinds of pieces, which may be nested to any
        depth and concatenated freely:
        * lowercase letters a-z, which stand for themselves;
        * k[...], where k is a positive decimal integer (possibly several
          digits): the fully expanded content of the brackets repeated k times;
        * <...>: the fully expanded content of the angle brackets, reversed.

        `s` is always well-formed. Empty brackets are allowed.

        >>> expand("3[ab]")
        'ababab'
        >>> expand("2[ab]<cd>")
        'ababdc'
        >>> expand("<a2[bc]>")
        'cbcba'
        >>> expand("2[x<3[yz]q>]")
        'xqzyzyzyxqzyzyzy'
        """
    ''',
    solution='''
    def expand(s: str) -> str:
        stack = [[]]
        modes = []
        number = ""
        for ch in s:
            if ch.isdigit():
                number += ch
            elif ch == "[":
                modes.append(int(number))
                number = ""
                stack.append([])
            elif ch == "<":
                modes.append(None)
                stack.append([])
            elif ch == "]":
                piece = "".join(stack.pop()) * modes.pop()
                stack[-1].append(piece)
            elif ch == ">":
                modes.pop()
                piece = "".join(stack.pop())[::-1]
                stack[-1].append(piece)
            else:
                stack[-1].append(ch)
        return "".join(stack[0])
    ''',
    cases=[("3[ab]",), ("2[ab]<cd>",), ("<a2[bc]>",), ("2[x<3[yz]q>]",), ("",), ("abc",), ("<>",), ("5[]",),
           ("12[a]",), ("<<abc>>",), ("2[<ab>3[c]]d",), ("<2[ab<cd>]e>",), ("1[1[1[z]]]",),
           ("a2[b2[c2[d<ef>]]]g",), ("<a<b<c<d>>>>",), ("10[<xy>]2[z]",)],
    brute=_brute_expand, fuzz=_fuzz_expand,
)

# ----------------------------------------------------------------------------- 14


def _brute_jobs(jobs):
    best = 0
    for mask in range(1 << len(jobs)):
        chosen = sorted(jobs[i] for i in range(len(jobs)) if mask >> i & 1)
        if all(chosen[i][1] <= chosen[i + 1][0] for i in range(len(chosen) - 1)):
            best = max(best, sum(job[2] for job in chosen))
    return best


def _fuzz_jobs(nxt):
    jobs = []
    for _ in range(nxt(10)):
        start = nxt(20)
        jobs.append((start, start + 1 + nxt(8), 1 + nxt(30)))
    return (jobs,)


problem(
    task_id="sixcat-v2/14", entry="max_profit",
    prompt='''
    def max_profit(jobs: list) -> int:
        """Each job is (start, end, profit) with integers start < end and
        profit >= 1. A job occupies the half-open time interval [start, end),
        so a job may begin exactly when another one ends.

        Return the largest total profit of a set of jobs in which no two jobs
        overlap in time. The answer for an empty list is 0. There can be up to
        100,000 jobs with times below 2 * 10**9.

        >>> max_profit([(1, 3, 50), (2, 5, 20), (3, 6, 70), (6, 19, 100)])
        220
        >>> max_profit([(0, 10, 5), (0, 5, 3), (5, 10, 3)])
        6
        >>> max_profit([(1, 4, 9), (2, 3, 4), (3, 5, 4)])
        9
        """
    ''',
    solution='''
    import bisect


    def max_profit(jobs: list) -> int:
        ordered = sorted(jobs, key=lambda job: job[1])
        ends = [job[1] for job in ordered]
        best = [0] * (len(ordered) + 1)
        for index, (start, end, profit) in enumerate(ordered):
            fits = bisect.bisect_right(ends, start, 0, index)
            take = best[fits] + profit
            best[index + 1] = take if take > best[index] else best[index]
        return best[-1]
    ''',
    cases=[([(1, 3, 50), (2, 5, 20), (3, 6, 70), (6, 19, 100)],), ([(0, 10, 5), (0, 5, 3), (5, 10, 3)],),
           ([(1, 4, 9), (2, 3, 4), (3, 5, 4)],), ([],), ([(5, 6, 7)],),
           ([(1, 2, 5), (1, 2, 6), (1, 2, 4)],), ([(1, 3, 5), (3, 5, 5), (5, 7, 5), (2, 6, 14)],),
           ([(0, 1000000000, 1), (0, 1, 1), (1, 2, 1), (999999999, 1000000000, 1)],),
           ([(4, 7, 10), (1, 5, 8), (6, 9, 8), (0, 2, 3), (8, 10, 6), (2, 4, 4)],)],
    brute=_brute_jobs, fuzz=_fuzz_jobs,
    perf=['''
    nxt = _rng(1414)
    jobs = []
    for _ in range(100000):
        start = nxt(1000000000)
        jobs.append((start, start + 1 + nxt(20000), 1 + nxt(1000)))
    args = (jobs,)
    '''],
)

# ----------------------------------------------------------------------------- 15


def _brute_kth(s, k):
    ordered = sorted(set(itertools.permutations(s)))
    return "".join(ordered[k - 1]) if 1 <= k <= len(ordered) else ""


problem(
    task_id="sixcat-v2/15", entry="kth_arrangement",
    prompt='''
    def kth_arrangement(s: str, k: int) -> str:
        """Consider every distinct string that can be made by rearranging all
        the characters of `s`, sorted in ascending lexicographic order (ordinary
        Python string order). Return the k-th of them, counting from k = 1.
        Return "" if there are fewer than k distinct arrangements.

        `s` has 1 to 30 lowercase letters, possibly with repeats, and
        1 <= k <= 10**18, so the arrangements cannot be listed one by one.

        >>> kth_arrangement("abc", 4)
        'bca'
        >>> kth_arrangement("aab", 2)
        'aba'
        >>> kth_arrangement("aab", 4)
        ''
        >>> kth_arrangement("banana", 37)
        'bnaaan'
        """
    ''',
    solution='''
    from math import factorial


    def kth_arrangement(s: str, k: int) -> str:
        counts = {}
        for ch in s:
            counts[ch] = counts.get(ch, 0) + 1

        def ways(total):
            result = factorial(total)
            for value in counts.values():
                result //= factorial(value)
            return result

        if k > ways(len(s)):
            return ""
        out = []
        for remaining in range(len(s), 0, -1):
            for ch in sorted(counts):
                if not counts[ch]:
                    continue
                counts[ch] -= 1
                block = ways(remaining - 1)
                if k <= block:
                    out.append(ch)
                    break
                k -= block
                counts[ch] += 1
        return "".join(out)
    ''',
    cases=[("abc", 4), ("aab", 2), ("aab", 4), ("banana", 37), ("a", 1), ("a", 2), ("zzzz", 1), ("zzzz", 2),
           ("cba", 1), ("cba", 6), ("aabbcc", 90), ("aabbcc", 91), ("abcdefg", 5040), ("abcdefg", 2771)],
    big=[("mississippi", 34650), ("mississippi", 34651), ("mississippi", 12345),
         ("abcdefghijklmnopqrstuvwxyzabcd", 10 ** 18), ("aaaaaaaaaaaaaaabbbbbbbbbbbbbbb", 155117520),
         ("aaaaaaaaaaaaaaabbbbbbbbbbbbbbb", 155117521), ("thequickbrownfoxjumpsoverlazyd", 987654321987654321)],
    brute=_brute_kth,
    fuzz=lambda nxt: ("".join("abc"[nxt(3)] for _ in range(1 + nxt(6))), 1 + nxt(140)),
)

# ----------------------------------------------------------------------------- 16


def _second_hull(points):
    pts = sorted(set(map(tuple, points)))
    if len(pts) < 3:
        return 0

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def dist2(a, b):
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    start = pts[0]
    hull, current = [], start
    while True:
        hull.append(current)
        candidate = None
        for p in pts:
            if p == current:
                continue
            if candidate is None:
                candidate = p
                continue
            turn = cross(current, candidate, p)
            if turn < 0 or (turn == 0 and dist2(current, p) > dist2(current, candidate)):
                candidate = p
        current = candidate
        if current == start or len(hull) > len(pts):
            break
    area = 0
    for i in range(len(hull)):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % len(hull)]
        area += x1 * y2 - x2 * y1
    return abs(area)


problem(
    task_id="sixcat-v2/16", entry="hull_area_doubled",
    prompt='''
    def hull_area_doubled(points: list) -> int:
        """Return twice the area of the convex hull of the given points, as an
        integer.

        `points` is a list of (x, y) pairs with integer coordinates between
        -10**6 and 10**6. Points may repeat. If fewer than three distinct points
        are given, or all points lie on one straight line, the answer is 0.
        (Twice the area of a polygon with integer vertices is always an
        integer.) There can be up to 100,000 points.

        >>> hull_area_doubled([(0, 0), (4, 0), (0, 3)])
        12
        >>> hull_area_doubled([(0, 0), (2, 0), (2, 2), (0, 2), (1, 1)])
        8
        >>> hull_area_doubled([(0, 0), (1, 1), (2, 2), (5, 5)])
        0
        """
    ''',
    solution='''
    def hull_area_doubled(points: list) -> int:
        pts = sorted(set((x, y) for x, y in points))
        if len(pts) < 3:
            return 0

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        lower = []
        for p in pts:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)
        upper = []
        for p in reversed(pts):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)
        hull = lower[:-1] + upper[:-1]
        total = 0
        for i in range(len(hull)):
            x1, y1 = hull[i]
            x2, y2 = hull[(i + 1) % len(hull)]
            total += x1 * y2 - x2 * y1
        return abs(total)
    ''',
    cases=[([(0, 0), (4, 0), (0, 3)],), ([(0, 0), (2, 0), (2, 2), (0, 2), (1, 1)],),
           ([(0, 0), (1, 1), (2, 2), (5, 5)],), ([],), ([(3, 3)],), ([(1, 1), (1, 1), (1, 1)],),
           ([(0, 0), (0, 5), (0, 5), (0, -2)],), ([(-1, -1), (1, -1), (1, 1), (-1, 1)],),
           ([(0, 0), (10, 0), (5, 1), (5, -1), (5, 0), (2, 0), (8, 0)],),
           ([(-1000000, -1000000), (1000000, -1000000), (1000000, 1000000), (-1000000, 1000000)],),
           ([(0, 0), (3, 0), (6, 0), (6, 3), (6, 6), (3, 6), (0, 6), (0, 3), (3, 3)],),
           ([(1, 0), (2, 3), (4, 1), (3, 5), (0, 4), (2, 2)],)],
    brute=_second_hull,
    fuzz=lambda nxt: ([(nxt(9) - 4, nxt(9) - 4) for _ in range(nxt(12))],),
    perf=['''
    nxt = _rng(1616)
    args = ([(nxt(2000001) - 1000000, nxt(2000001) - 1000000) for _ in range(100000)],)
    ''', '''
    args = ([(i, i * i % 1000003) for i in range(-50000, 50000)],)
    '''],
)

# ----------------------------------------------------------------------------- 17


def _brute_window(nums, limit):
    best = 0
    for i in range(len(nums)):
        low = high = nums[i]
        for j in range(i, len(nums)):
            low, high = min(low, nums[j]), max(high, nums[j])
            if high - low > limit:
                break
            best = max(best, j - i + 1)
    return best


problem(
    task_id="sixcat-v2/17", entry="longest_steady_run",
    prompt='''
    def longest_steady_run(nums: list, limit: int) -> int:
        """Return the length of the longest contiguous run of `nums` in which
        the largest value minus the smallest value is at most `limit`.

        `nums` is a list of integers (possibly empty, possibly negative) and
        `limit` >= 0. An empty list gives 0. The list can hold up to 200,000
        values, so checking every run is too slow.

        >>> longest_steady_run([8, 2, 4, 7], 4)
        2
        >>> longest_steady_run([10, 1, 2, 4, 7, 2], 5)
        4
        >>> longest_steady_run([4, 2, 2, 2, 4, 4, 2, 2], 0)
        3
        """
    ''',
    solution='''
    from collections import deque


    def longest_steady_run(nums: list, limit: int) -> int:
        highs, lows = deque(), deque()
        left = best = 0
        for right, value in enumerate(nums):
            while highs and nums[highs[-1]] <= value:
                highs.pop()
            highs.append(right)
            while lows and nums[lows[-1]] >= value:
                lows.pop()
            lows.append(right)
            while nums[highs[0]] - nums[lows[0]] > limit:
                left += 1
                if highs[0] < left:
                    highs.popleft()
                if lows[0] < left:
                    lows.popleft()
            if right - left + 1 > best:
                best = right - left + 1
        return best
    ''',
    cases=[([8, 2, 4, 7], 4), ([10, 1, 2, 4, 7, 2], 5), ([4, 2, 2, 2, 4, 4, 2, 2], 0), ([], 3), ([5], 0),
           ([1, 2, 3, 4, 5], 100), ([-5, -1, -9, 0, 3, -2], 4), ([7, 7, 7, 7], 0), ([1, 5, 1, 5, 1, 5], 3),
           ([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9], 3)],
    brute=_brute_window,
    fuzz=lambda nxt: ([nxt(21) - 10 for _ in range(nxt(16))], nxt(8)),
    perf=['''
    nxt = _rng(1717)
    args = ([nxt(1000000) for _ in range(200000)], 250000)
    ''', '''
    args = (list(range(200000)), 150000)
    '''],
)

# ----------------------------------------------------------------------------- 18


def _brute_xor_sub(nums):
    best = 0
    for i in range(len(nums)):
        acc = 0
        for j in range(i, len(nums)):
            acc ^= nums[j]
            best = max(best, acc)
    return best


problem(
    task_id="sixcat-v2/18", entry="max_xor_run",
    prompt='''
    def max_xor_run(nums: list) -> int:
        """Return the largest value obtainable by XOR-ing together all the
        elements of some non-empty contiguous run of `nums`.

        `nums` holds between 1 and 30,000 non-negative integers below 2**30.
        Trying every run is too slow at that size.

        >>> max_xor_run([1, 2, 3, 4])
        7
        >>> max_xor_run([8, 1, 2, 12, 7, 6])
        15
        >>> max_xor_run([4, 6])
        6
        >>> max_xor_run([0])
        0
        """
    ''',
    solution='''
    def max_xor_run(nums: list) -> int:
        prefixes = [0]
        acc = 0
        for value in nums:
            acc ^= value
            prefixes.append(acc)
        best = 0
        for bit in range(29, -1, -1):
            best <<= 1
            want = best | 1
            seen = set()
            found = False
            for prefix in prefixes:
                top = prefix >> bit
                if top ^ want in seen:
                    found = True
                    break
                seen.add(top)
            if found:
                best = want
        return best
    ''',
    cases=[([1, 2, 3, 4],), ([8, 1, 2, 12, 7, 6],), ([4, 6],), ([0],), ([0, 0, 0],), ([5],),
           ([2 ** 30 - 1, 2 ** 30 - 1],), ([1, 1, 1, 1, 1],), ([3, 8, 15, 17, 2, 9, 31],),
           ([1023, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1],)],
    brute=_brute_xor_sub,
    fuzz=lambda nxt: ([nxt(1 << (1 + nxt(9))) for _ in range(1 + nxt(12))],),
    perf=['''
    nxt = _rng(1818)
    args = ([nxt(1 << 30) for _ in range(30000)],)
    ''', '''
    args = ([1 << (i % 30) for i in range(30000)],)
    '''],
)

# ----------------------------------------------------------------------------- 19


def _brute_install(deps):
    need = {name: set(values) for name, values in deps.items()}
    for values in deps.values():
        for name in values:
            need.setdefault(name, set())
    order, done = [], set()
    while len(order) < len(need):
        ready = sorted(name for name in need if name not in done and need[name] <= done)
        if not ready:
            return []
        order.append(ready[0])
        done.add(ready[0])
    return order


def _fuzz_install(nxt):
    names = ["a", "b", "c", "d", "e", "f", "g"]
    deps = {}
    for _ in range(nxt(6)):
        deps[names[nxt(7)]] = [names[nxt(7)] for _ in range(nxt(3))]
    return (deps,)


problem(
    task_id="sixcat-v2/19", entry="install_order",
    prompt='''
    def install_order(deps: dict) -> list:
        """`deps` maps a package name to the list of packages it depends on.
        A package that appears only inside some dependency list (and not as a
        key) is still a package; it simply has no dependencies. A dependency
        list may contain repeats.

        Return a list containing every package exactly once, such that each
        package comes after all of its dependencies. Build the list one package
        at a time, always choosing the alphabetically smallest package (ordinary
        Python string order) among those whose dependencies are all already in
        the list. If the dependencies contain a cycle (including a package that
        depends on itself), return an empty list.

        >>> install_order({"app": ["lib", "util"], "lib": ["core"], "util": ["core"]})
        ['core', 'lib', 'util', 'app']
        >>> install_order({"b": ["a"], "c": [], "a": []})
        ['a', 'b', 'c']
        >>> install_order({"x": ["y"], "y": ["x"]})
        []
        >>> install_order({})
        []
        """
    ''',
    solution='''
    import heapq


    def install_order(deps: dict) -> list:
        needs = {}
        for name, values in deps.items():
            needs.setdefault(name, set()).update(values)
            for value in values:
                needs.setdefault(value, set())
        dependents = {name: [] for name in needs}
        waiting = {}
        for name, values in needs.items():
            waiting[name] = len(values)
            for value in values:
                dependents[value].append(name)
        ready = [name for name, count in waiting.items() if count == 0]
        heapq.heapify(ready)
        order = []
        while ready:
            name = heapq.heappop(ready)
            order.append(name)
            for other in dependents[name]:
                waiting[other] -= 1
                if waiting[other] == 0:
                    heapq.heappush(ready, other)
        return order if len(order) == len(needs) else []
    ''',
    cases=[({"app": ["lib", "util"], "lib": ["core"], "util": ["core"]},), ({"b": ["a"], "c": [], "a": []},),
           ({"x": ["y"], "y": ["x"]},), ({},), ({"solo": []},), ({"self": ["self"]},),
           ({"z": ["a", "a", "m"], "m": ["a"]},), ({"d": ["c"], "c": ["b"], "b": ["a"], "e": []},),
           ({"web": ["db", "cache"], "db": ["os"], "cache": ["os", "net"], "net": ["os"], "cli": ["os"]},),
           ({"a": ["b"], "b": ["c"], "c": ["a"], "d": []},), ({"B": ["a"], "a": ["C"], "b": ["B"]},)],
    brute=_brute_install, fuzz=_fuzz_install,
    perf=['''
    nxt = _rng(1919)
    deps = {}
    for i in range(1, 20000):
        deps["p%05d" % i] = ["p%05d" % nxt(i) for _ in range(1 + nxt(3))]
    args = (deps,)
    '''],
)

# ----------------------------------------------------------------------------- 20


def _brute_duration(text):
    units = "dhms"
    scale = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    i, n = 0, len(text)
    total, last, seen = 0, -1, 0
    while True:
        while i < n and text[i] == " ":
            i += 1
        if i == n:
            break
        j = i
        while j < n and text[j] in "0123456789":
            j += 1
        if j == i or j == n or text[j] not in units:
            raise ValueError(text)
        rank = units.index(text[j])
        if rank <= last:
            raise ValueError(text)
        last = rank
        total += int(text[i:j]) * scale[text[j]]
        seen += 1
        i = j + 1
    if not seen:
        raise ValueError(text)
    return total


def _fuzz_duration(nxt):
    parts = []
    for unit in "dhms":
        if nxt(2):
            parts.append(f"{nxt(200)}{unit}")
    if nxt(6) == 0 and len(parts) > 1:
        parts.reverse()
    text = [" " * nxt(3)]
    for part in parts:
        text.append(part + " " * nxt(3))
    return ("".join(text),)


problem(
    task_id="sixcat-v2/20", entry="parse_duration",
    prompt='''
    def parse_duration(text: str) -> int:
        """Convert a duration such as "1d 2h 30m 15s" into a total number of
        seconds.

        A valid duration is one or more components. A component is one or more
        digits 0-9 immediately followed by one unit letter: d (86400 seconds),
        h (3600), m (60) or s (1). Unit letters are lowercase only.

        * Components must appear in the order d, h, m, s, and each unit may be
          used at most once (so "2h30m" is valid; "30m2h" and "1h1h" are not).
        * Components may be separated by any number of spaces, including none.
          Leading and trailing spaces are allowed. A space between a number and
          its unit is not allowed.
        * Leading zeros in a number are allowed ("007m" is 420 seconds).
        * Nothing else may appear: no signs, decimal points, other letters or
          other whitespace.

        Raise ValueError for any string that is not a valid duration, including
        the empty string and a string of only spaces.

        >>> parse_duration("1d 2h 30m 15s")
        95415
        >>> parse_duration("90m")
        5400
        >>> parse_duration(" 2h30m ")
        9000
        >>> parse_duration("0s")
        0
        """
    ''',
    solution='''
    import re


    def parse_duration(text: str) -> int:
        match = re.fullmatch(r" *(?:([0-9]+)d)? *(?:([0-9]+)h)? *(?:([0-9]+)m)? *(?:([0-9]+)s)? *", text)
        if not match or all(group is None for group in match.groups()):
            raise ValueError("invalid duration: %r" % (text,))
        total = 0
        for group, scale in zip(match.groups(), (86400, 3600, 60, 1)):
            if group is not None:
                total += int(group) * scale
        return total
    ''',
    cases=[("1d 2h 30m 15s",), ("90m",), (" 2h30m ",), ("0s",), ("007m",), ("1d2h3m4s",), ("3d   4s",),
           ("12h",), ("100d 100h 100m 100s",), ("5m 5s",), ("1d1s",), ("   9s",), ("0d0h0m0s",)],
    raises=["", "   ", "5", "h", "1h1h", "30m2h", "1 h", "-1h", "1.5h", "1H", "1h 30", "1h, 30m", "1h\t30m",
            "1h\n", "2w", "1s1d", "h1", "1d 2h 3m 4s 5s", "1dd", "+3m", "1h30"],
    brute=_brute_duration, fuzz=_fuzz_duration,
)


# ----------------------------------------------------------------------------- build

def _load(spec: dict):
    namespace: dict = {}
    exec(spec["solution"], namespace)
    return namespace[spec["entry"]]


def _call(function, args):
    try:
        return ("ok", _n(function(*args)))
    except ValueError:
        return ("raises", None)


def _perf_args(snippet: str):
    namespace = {"_rng": _rng}
    exec(textwrap.dedent(snippet), namespace)
    return namespace["args"]


def _check_docstring_examples(spec: dict) -> None:
    """Every `>>>` example shown to the model must be true of the reference solution."""
    stub: dict = {}
    exec(spec["prompt"], stub)
    namespace: dict = {}
    exec(spec["solution"], namespace)
    test = doctest.DocTestParser().get_doctest(stub[spec["entry"]].__doc__, namespace, spec["task_id"], None, 0)
    if not test.examples:
        raise AssertionError(f"{spec['task_id']}: prompt has no examples")
    runner = doctest.DocTestRunner(verbose=False)
    runner.run(test, out=lambda text: None)
    if runner.failures:
        raise AssertionError(f"{spec['task_id']}: {runner.failures} docstring example(s) disagree with the reference")


def _verify(spec: dict, reference) -> None:
    _check_docstring_examples(spec)
    nxt = _rng(int(spec["task_id"].split("/")[1]) * 7919 + 17)
    for _ in range(400):
        args = spec["fuzz"](nxt)
        expected = _call(spec["brute"], args)
        got = _call(reference, args)
        if expected != got:
            raise AssertionError(f"{spec['task_id']}: reference {got!r} != brute {expected!r} for {args!r}")
    for args in spec["cases"]:
        outcome = _call(reference, args)
        if outcome[0] != "ok":
            raise AssertionError(f"{spec['task_id']}: case {args!r} unexpectedly raises")
        if outcome != _call(spec["brute"], args):
            raise AssertionError(f"{spec['task_id']}: brute disagrees on case {args!r}")
    for args in spec["big"]:
        if _call(reference, args)[0] != "ok":
            raise AssertionError(f"{spec['task_id']}: big case {args!r} unexpectedly raises")
    for bad in spec["raises"]:
        if _call(reference, (bad,))[0] != "raises" or _call(spec["brute"], (bad,))[0] != "raises":
            raise AssertionError(f"{spec['task_id']}: {bad!r} should raise ValueError")


def _test_source(spec: dict, reference) -> str:
    lines = [PRELUDE, "", "def check(candidate):"]
    for args in spec["cases"] + spec["big"]:
        expected = _n(reference(*args))
        rendered = ", ".join(repr(arg) for arg in args)
        lines.append(f"    assert _n(candidate({rendered})) == {expected!r}")
    for bad in spec["raises"]:
        lines += [
            "    try:",
            f"        candidate({bad!r})",
            "    except ValueError:",
            "        pass",
            "    else:",
            f"        raise AssertionError({bad!r})",
        ]
    for snippet in spec["perf"]:
        body = textwrap.dedent(snippet).strip("\n")
        expected = _n(reference(*_perf_args(snippet)))
        lines += ["    " + line for line in body.splitlines()]
        if len(repr(expected)) > 120:
            # Large outputs are compared by digest so the data file stays small.
            lines.append(f"    assert _digest(candidate(*args)) == {_digest(expected)!r}")
        else:
            lines.append(f"    assert _n(candidate(*args)) == {expected!r}")
    return "\n".join(lines) + "\n"


def build() -> list[dict]:
    rows = []
    for spec in PROBLEMS:
        reference = _load(spec)
        _verify(spec, reference)
        rows.append({
            "task_id": spec["task_id"],
            "entry_point": spec["entry"],
            "prompt": spec["prompt"],
            "canonical_solution": spec["solution"],
            "test": _test_source(spec, reference),
        })
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
    print(f"wrote {OUT} ({len(PROBLEMS)} problems)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
