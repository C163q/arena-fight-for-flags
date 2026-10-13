"""Exact single-seat and ordered-pair balance for two to eight participants."""
from collections import Counter
from itertools import product


def permutations_for(n, mode):
    """Return permutations mapping participant index to map team_id."""
    if type(n) is not int or not 2 <= n <= 8 or mode not in ('balanced', 'quick'):
        raise ValueError('players must be 2..8 and mode balanced/quick')
    if mode == 'quick':
        return [tuple((i + shift) % n for i in range(n)) for shift in range(n)]
    if n == 6:
        rows = set()
        for a, b, c, d in product(range(5), repeat=4):
            if (a*d - b*c) % 5 != 1:
                continue
            row = []
            for x in range(6):
                num, den = (a, c) if x == 5 else ((a*x+b) % 5, (c*x+d) % 5)
                row.append(5 if den == 0 else num * pow(den, -1, 5) % 5)
            rows.add(tuple(row))
        return sorted(rows)

    def multiply(a, b):
        if n not in (4, 8):
            return a*b % n
        result = 0
        while b:
            if b & 1:
                result ^= a
            b >>= 1
            a <<= 1
            if a & n:
                a ^= {4: 7, 8: 11}[n]
        return result

    return [tuple((multiply(a, x) ^ b) if n in (4, 8) else (multiply(a, x)+b) % n
                  for x in range(n)) for a in range(1, n) for b in range(n)]


def coverage(rows):
    """Count all cells, including missing pairs, rather than only observed cells."""
    if not rows:
        raise ValueError('empty schedule')
    n = len(rows[0])
    if any(sorted(row) != list(range(n)) for row in rows):
        raise ValueError('invalid schedule permutation')
    single = Counter((i, row[i]) for row in rows for i in range(n))
    pair = Counter((i, j, row[i], row[j]) for row in rows for i in range(n) for j in range(n) if i != j)
    single_values = [single[i, s] for i in range(n) for s in range(n)]
    pair_values = [pair[i, j, s, t] for i in range(n) for j in range(n) if i != j
                   for s in range(n) for t in range(n) if s != t]
    return {'matches': len(rows), 'single_min': min(single_values), 'single_max': max(single_values),
            'pair_min': min(pair_values), 'pair_max': max(pair_values),
            'pair_coverage': len(pair) / len(pair_values)}
