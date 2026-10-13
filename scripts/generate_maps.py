"""Reproduce the fixed diamond-ring RON maps and their geometric measurements."""
import argparse
from collections import deque
from fractions import Fraction
import json
from pathlib import Path

SIZES = {2: 25, 3: 29, 4: 31, 5: 33, 6: 35, 7: 37, 8: 41}
FLAG_RADII = {2: 4, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9, 8: 11}
# Calibrated from five seeded baseline self-play games per map; see docs/map-balance-2026-10-13.md.
LIMITS = {2: 400, 3: 500, 4: 600, 5: 700, 6: 800, 7: 900, 8: 1000}
DIRECTIONS = {
    2: [(7, 2), (-7, -2)],
    3: [(9, 2), (-5, 6), (-2, -9)],
    4: [(10, 2), (-2, 10), (-10, -2), (2, -10)],
    5: [(7, 6), (-4, 9), (-11, 2), (-3, -10), (7, -6)],
    6: [(11, 3), (3, 11), (-7, 7), (-11, -3), (-3, -11), (7, -7)],
    7: [(8, 7), (-2, 13), (-9, 6), (-11, -4), (-4, -11), (6, -9), (13, -2)],
    8: [(14, 3), (7, 10), (-3, 14), (-10, 7), (-14, -3), (-7, -10), (3, -14), (10, -7)],
}


def diamond(radius, direction):
    """Scale fixed integer directions to an exact Manhattan radius."""
    x, y = direction
    a = round(Fraction(radius * abs(x), abs(x) + abs(y)))
    return a * (1 if x >= 0 else -1), (radius - a) * (1 if y >= 0 else -1)


def distances(grid, starts):
    result = {p: 0 for p in starts}
    queue = deque(starts)
    while queue:
        x, y = queue.popleft()
        for p in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            a, b = p
            if 0 <= b < len(grid) and 0 <= a < len(grid[0]) and grid[b][a] == '.' and p not in result:
                result[p] = result[x, y] + 1
                queue.append(p)
    return result


def home_cells(home):
    return [(home['x'] + dx, home['y'] + dy) for dy in range(3) for dx in range(3)]


def metrics(game_map):
    grid = game_map['terrain']
    matrix, home_matrix = [], []
    floor_count = sum(row.count('.') for row in grid)
    for home in game_map['spawn_regions']:
        d = distances(grid, home_cells(home))
        if len(d) != floor_count:
            raise ValueError('disconnected terrain')
        matrix.append([d[f['x'], f['y']] for f in game_map['flag_points']])
        home_matrix.append([min(d[p] for p in home_cells(h)) for h in game_map['spawn_regions']])
    nearest = [min(row) for row in matrix]
    means = [sum(row) / len(row) for row in matrix]
    walls = sum(row.count('#') for row in grid) - (game_map['width'] + game_map['height']) * 2 + 4
    return {'distance_to_flags': matrix, 'distance_to_homes': home_matrix,
            'nearest_flag': nearest, 'nearest_spread': max(nearest) - min(nearest),
            'mean_flag_distance': means, 'mean_spread': max(means) - min(means),
            'interior_walls': walls, 'interior_wall_fraction': walls / (len(grid) - 2) ** 2}


def shuffled_cells(size, seed):
    cells = [(x, y) for y in range(2, size - 2) for x in range(2, size - 2)]
    mask = (1 << 64) - 1
    for i in range(len(cells) - 1, 0, -1):
        seed = (seed + 0x9E3779B97F4A7C15) & mask
        z = seed
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & mask
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
        z ^= z >> 31
        j = z % (i + 1)
        cells[i], cells[j] = cells[j], cells[i]
    return cells


def make_map(players, max_turns=None):
    size = SIZES[players]
    center, radius = size // 2, size // 2 - 3
    grid = [['#' if x in (0, size - 1) or y in (0, size - 1) else '.' for x in range(size)] for y in range(size)]
    homes, flags = [], [{'id': 0, 'x': center, 'y': center}]
    for team in range(players):
        direction = DIRECTIONS[players][team]
        x, y = diamond(radius, direction)
        homes.append({'team_id': team, 'x': center + x - 1, 'y': center + y - 1, 'width': 3, 'height': 3})
        x, y = diamond(FLAG_RADII[players], direction)
        flags.append({'id': team + 1, 'x': center + x, 'y': center + y})
    game_map = {'format_version': 1, 'id': f'arena_{players}p', 'players': players,
                'match_limits': {'target_score': 20, 'max_turns': LIMITS[players] if max_turns is None else max_turns},
                'width': size, 'height': size, 'terrain': grid, 'spawn_regions': homes, 'flag_points': flags}
    original = metrics(game_map)['distance_to_flags']
    protected = set()
    for home in homes:
        protected.update((home['x'] + dx, home['y'] + dy) for dy in range(-1, 4) for dx in range(-1, 4))
    walls, wanted = [], round((size - 2) ** 2 * .04)
    for x, y in shuffled_cells(size, 0xFFF20261013 + players):
        if (x, y) in protected or abs(x - center) + abs(y - center) <= FLAG_RADII[players] + 1:
            continue
        if any(max(abs(x - a), abs(y - b)) < 3 for a, b in walls):
            continue
        grid[y][x] = '#'
        try:
            unchanged = metrics(game_map)['distance_to_flags'] == original
        except ValueError:
            unchanged = False
        if not unchanged:
            grid[y][x] = '.'
            continue
        walls.append((x, y))
        if len(walls) == wanted:
            break
    if len(walls) != wanted:
        raise ValueError(f'{players}p: cannot place requested sparse cover')
    game_map['terrain'] = [''.join(row) for row in grid]
    return game_map


def ron(game_map):
    m = game_map
    lines = ['// Fixed diamond-ring arena v2. Reproduce with scripts/generate_maps.py.',
             '// Border sealed; sparse cover preserves home-to-flag shortest distances.', '(',
             '    format_version: 1,', f'    id: "{m["id"]}",', f'    players: {m["players"]},',
             f'    match_limits: (target_score: 20, max_turns: {m["match_limits"]["max_turns"]}),',
             f'    width: {m["width"]},', f'    height: {m["height"]},', '    terrain: [']
    lines += [f'        "{row}",' for row in m['terrain']]
    lines += ['    ],', '    spawn_regions: [']
    lines += ['        (' + ', '.join(f'{k}: {v}' for k, v in home.items()) + '),' for home in m['spawn_regions']]
    lines += ['    ],', '    flag_points: [']
    lines += ['        (' + ', '.join(f'{k}: {v}' for k, v in flag.items()) + '),' for flag in m['flag_points']]
    return '\n'.join(lines + ['    ],', ')', ''])


def overview(maps):
    colors = ['#67c9a5', '#f48175', '#79aef2', '#d09cf2', '#f0bd65', '#6fd2df', '#ed94be', '#a8c66e']
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1320" viewBox="0 0 1200 1320">',
             '<rect width="1200" height="1320" fill="#0b1117"/>',
             '<style>text{font-family:system-ui,sans-serif;fill:#e4edf4}</style>']
    for i, m in enumerate(maps):
        ox, oy, cell = (i % 3) * 400 + 22, (i // 3) * 440 + 45, 350 / m['width']
        stats = metrics(m)
        parts += [f'<text x="{ox}" y="{oy-20}" font-size="19">{m["players"]} teams · {m["width"]} × {m["height"]} · 20 / {m["match_limits"]["max_turns"]}</text>',
                  f'<rect x="{ox}" y="{oy}" width="350" height="350" fill="#15232e"/>']
        for y, row in enumerate(m['terrain']):
            for x, tile in enumerate(row):
                if tile == '#':
                    parts.append(f'<rect x="{ox+x*cell:.2f}" y="{oy+y*cell:.2f}" width="{cell+.1:.2f}" height="{cell+.1:.2f}" fill="#405365"/>')
        for h in m['spawn_regions']:
            parts += [f'<rect x="{ox+h["x"]*cell:.2f}" y="{oy+h["y"]*cell:.2f}" width="{3*cell:.2f}" height="{3*cell:.2f}" fill="{colors[h["team_id"]]}" opacity=".5"/>',
                      f'<text x="{ox+(h["x"]+1.5)*cell:.2f}" y="{oy+(h["y"]+2)*cell:.2f}" text-anchor="middle" font-size="13">{h["team_id"]}</text>']
        for f in m['flag_points']:
            parts.append(f'<circle cx="{ox+(f["x"]+.5)*cell:.2f}" cy="{oy+(f["y"]+.5)*cell:.2f}" r="4" fill="#ffd166"/>')
        parts.append(f'<text x="{ox}" y="{oy+375}" font-size="13">Nearest flag: {", ".join(map(str,stats["nearest_flag"]))}</text>')
    return '\n'.join(parts + ['</svg>'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('maps'))
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--metrics', type=Path)
    parser.add_argument('--overview', type=Path)
    args = parser.parse_args()
    maps = [make_map(n) for n in range(2, 9)]
    if not args.check:
        args.out.mkdir(parents=True, exist_ok=True)
    for m in maps:
        path = args.out / (m['id'] + '.ron')
        if args.check:
            if path.read_text() != ron(m):
                parser.error(f'generated map differs: {path}')
        else:
            path.write_text(ron(m))
        print(m['id'], json.dumps(metrics(m), separators=(',', ':')), flush=True)
    if args.metrics:
        args.metrics.parent.mkdir(parents=True, exist_ok=True)
        args.metrics.write_text(json.dumps({m['id']: metrics(m) for m in maps}, indent=2) + '\n')
    if args.overview:
        args.overview.parent.mkdir(parents=True, exist_ok=True)
        args.overview.write_text(overview(maps))


if __name__ == '__main__':
    main()
