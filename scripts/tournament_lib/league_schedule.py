"""Exact candidate/seat and ordered candidate-pair/seat-pair designs."""
from collections import Counter
from functools import lru_cache
from itertools import combinations, product
from math import comb
from .schedule import permutations_for


def field(q):
    """Tiny polynomial fields used by the compact designs, q <= 256."""
    if q in (4, 8, 16, 32, 64, 128, 256):
        modulus = {4:7, 8:11, 16:19, 32:37, 64:67, 128:131, 256:285}[q]
        def mul(a, b):
            value = 0
            while b:
                if b & 1:
                    value ^= a
                a <<= 1
                if a & q:
                    a ^= modulus
                b >>= 1
            return value
        return lambda a,b:a^b, mul
    if q == 9:
        # F3[x]/(x^2+1), digits a0 + 3*a1.
        def add(a,b):
            return (a%3+b%3)%3 + 3*((a//3+b//3)%3)
        def mul(a,b):
            return (a%3*(b%3)-a//3*(b//3))%3 + 3*((a%3*(b//3)+a//3*(b%3))%3)
        return add, mul
    if q >= 2 and all(q % i for i in range(2, int(q**.5)+1)):
        return lambda a,b:(a+b)%q, lambda a,b:a*b%q
    return None


def projective(q):
    add, mul = field(q)
    negative = {x:next(y for y in range(q) if add(x,y) == 0) for x in range(q)}
    inverse = {x:next(y for y in range(1,q) if mul(x,y) == 1) for x in range(1,q)}
    rows = set()
    for a,b,c,d in product(range(q), repeat=4):
        if add(mul(a,d), negative[mul(b,c)]) != 1:
            continue
        row = []
        for x in range(q+1):
            num, den = (a,c) if x == q else (add(mul(a,x),b), add(mul(c,x),d))
            row.append(q if den == 0 else mul(num,inverse[den]))
        rows.add(tuple(row))
    return sorted(rows)


def cyclic_fifteen(k):
    """Meet-in-the-middle exact difference counts; no solver dependency."""
    unseen = set(combinations(range(15), k))
    orbits = []
    while unseen:
        base = min(unseen)
        orbit = sorted({tuple(sorted((x+s)%15 for x in base)) for s in range(15)})
        unseen.difference_update(orbit)
        counts = Counter(min((b-a)%15, (a-b)%15) for a,b in combinations(base,2))
        vector = tuple(counts[d]*len(orbit)//15 for d in range(1,8))
        orbits.append((vector,orbit))
    long = [(v,o) for v,o in orbits if len(o) == 15]
    short = [(v,o) for v,o in orbits if len(o) < 15]
    sums = {}
    for i,(a,_) in enumerate(long):
        for j in range(i,len(long)):
            b = long[j][0]
            sums.setdefault(tuple(x+y for x,y in zip(a,b)), (i,j))
    if k == 6:
        for v,o in short:
            target = tuple(5-x for x in v)
            if target in sums:
                i,j = sums[target]
                return o + long[i][1] + long[j][1]
    else:
        for v,o in short:
            target = tuple(6-x for x in v)
            for a,ij in sums.items():
                complement = tuple(x-y for x,y in zip(target,a))
                if complement in sums:
                    return o + [row for i in (*ij,*sums[complement]) for row in long[i][1]]
    raise ValueError('no exact cyclic design found')


def fifteen_blocks(k):
    if k in (5,6):
        return cyclic_fifteen(k)
    if k == 3:
        return sorted({tuple(sorted((a-1,b-1,(a^b)-1))) for a,b in combinations(range(1,16),2)})
    if k == 4:
        return sorted({tuple(sorted((x-1,y-1,z-1,(x^y^z)-1)))
                       for x,y,z in combinations(range(1,16),3) if x^y^z})
    hyperplanes = [tuple(x-1 for x in range(1,16) if (a&x).bit_count()%2 == 0) for a in range(1,16)]
    return hyperplanes if k == 7 else [tuple(x for x in range(15) if x not in h) for h in hyperplanes]


@lru_cache(maxsize=128, typed=True)
def schedule(candidates, players, max_rows=10000):
    if type(candidates) is not int or candidates < 1 or type(players) is not int or not 2 <= players <= 8:
        raise ValueError('positive candidates and players 2..8 required')
    if type(max_rows) is not int or max_rows < 1:
        raise ValueError('positive row limit required')
    n = max(candidates,players)
    if candidates <= players:
        rows = [tuple(row.index(s) for s in range(players)) for row in permutations_for(players,'balanced')]
        method = 'fixed-roster'
    elif players == 2:
        if n*(n-1) > max_rows:
            raise ValueError('ordered-pair schedule exceeds match limit')
        rows = [(a,b) for a in range(n) for b in range(n) if a != b]
        method = 'ordered-pairs'
    elif n <= 256 and field(n):
        if n*(n-1) > max_rows:
            raise ValueError('affine schedule exceeds match limit')
        add, mul = field(n)
        rows = [tuple(add(mul(a,x),b) for x in range(players)) for a in range(1,n) for b in range(n)]
        method = 'affine'
    elif n in (6,10,12,14):
        rows = [row[:players] for row in projective(n-1)]
        method = 'projective'
    else:
        method = 'geometry-or-cyclic' if n == 15 else 'complete-subsets'
        rotations = permutations_for(players,'balanced')
        if n == 15:
            blocks = fifteen_blocks(players)
        else:
            if comb(n,players)*len(rotations) > max_rows:
                raise ValueError('exact complete-subset schedule exceeds match limit; increase --match-limit')
            blocks = combinations(range(n),players)
        rows = [tuple(block[row.index(s)] for s in range(players)) for block in blocks for row in rotations]
    if len(rows) > max_rows:
        raise ValueError(f'exact schedule needs {len(rows)} matches, above limit {max_rows}')
    coverage(rows,candidates,players)
    return tuple(rows), method


def coverage(rows, candidates, players):
    singles, pairs, appearances, meetings = Counter(),Counter(),Counter(),Counter()
    for row in rows:
        if len(row) != players or len(set(row)) != players or any(type(a) is not int or not 0 <= a < max(candidates,players) for a in row):
            raise ValueError('invalid schedule row')
        for s,a in enumerate(row):
            if a >= candidates:
                continue
            appearances[a] += 1
            singles[a,s] += 1
            for t,b in enumerate(row):
                if b < candidates and a != b:
                    pairs[a,b,s,t] += 1
                    meetings[a,b] += 1
    single_values = [singles[a,s] for a in range(candidates) for s in range(players)]
    pair_values = [pairs[a,b,s,t] for a in range(candidates) for b in range(candidates) if a!=b
                   for s in range(players) for t in range(players) if s!=t]
    if not rows or min(single_values) == 0 or len(set(single_values)) != 1 or (pair_values and (min(pair_values) == 0 or len(set(pair_values)) != 1)):
        raise ValueError('schedule fails exact balance')
    return {'matches':len(rows), 'appearances_min':min(appearances.values()), 'appearances_max':max(appearances.values()),
            'seat_min':min(single_values), 'seat_max':max(single_values),
            'pair_min':min(meetings.values()) if meetings else None, 'pair_max':max(meetings.values()) if meetings else None,
            'pair_seat_min':min(pair_values) if pair_values else None, 'pair_seat_max':max(pair_values) if pair_values else None}
