"""Structural validation for every field consumed by the offline player."""
U32 = 2**32 - 1
U64 = 2**64 - 1


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}: expected integer {low}..{high}")
    return value


def obj(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected object")
    return value


def array(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label}: expected array")
    return value


def text(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: expected nonempty text")
    return value


def flag_id(value, label):
    return None if value is None else integer(value, 1, U64, label)


class Validator:
    def __init__(self, game_map):
        self.map = obj(game_map, "map.json")
        integer(game_map.get("format_version"), 1, 1, "map.json.format_version")
        self.width = integer(game_map.get("width"), 9, 128, "map.json.width")
        self.height = integer(game_map.get("height"), 9, 128, "map.json.height")
        self.players = integer(game_map.get("players"), 2, 8, "map.json.players")
        text(game_map.get("id"), "map.json.id")
        self.terrain = array(game_map.get("terrain"), "map.json.terrain")
        if len(self.terrain) != self.height or any(not isinstance(row, str) or len(row) != self.width or set(row) - {"#", "."} for row in self.terrain):
            raise ValueError("map.json.terrain: invalid dimensions or cells")
        if any(c != "#" for c in self.terrain[0] + self.terrain[-1]) or any(row[0] != "#" or row[-1] != "#" for row in self.terrain):
            raise ValueError("map.json.terrain: unsealed border")
        limits = obj(game_map.get("match_limits"), "map.json.match_limits")
        integer(limits.get("target_score"), 1, U32, "map.json.match_limits.target_score")
        self.max_turns = integer(limits.get("max_turns"), 1, 1000000, "map.json.match_limits.max_turns")
        homes = array(game_map.get("spawn_regions"), "map.json.spawn_regions")
        if len(homes) != self.players:
            raise ValueError("map.json.spawn_regions: wrong count")
        home_cells, teams = set(), set()
        for index, home in enumerate(homes):
            label = f"map.json.spawn_regions[{index}]"
            home = obj(home, label)
            team = integer(home.get("team_id"), 0, self.players - 1, label + ".team_id")
            if team in teams:
                raise ValueError(label + ": duplicate team")
            teams.add(team)
            x, y = self.point(home, label, walkable=True)
            integer(home.get("width"), 3, 3, label + ".width")
            integer(home.get("height"), 3, 3, label + ".height")
            for dy in range(3):
                for dx in range(3):
                    cell = self.point({"x": x + dx, "y": y + dy}, label, walkable=True)
                    if cell in home_cells:
                        raise ValueError(label + ": overlapping homes")
                    home_cells.add(cell)
        sites = array(game_map.get("flag_points"), "map.json.flag_points")
        if not 1 <= len(sites) <= 32:
            raise ValueError("map.json.flag_points: wrong count")
        self.site_ids, coordinates = set(), set()
        for index, site in enumerate(sites):
            label = f"map.json.flag_points[{index}]"
            site = obj(site, label)
            ident = integer(site.get("id"), 0, U32, label + ".id")
            cell = self.point(site, label, walkable=True)
            if ident in self.site_ids or cell in coordinates or cell in home_cells:
                raise ValueError(label + ": duplicate or home flag point")
            self.site_ids.add(ident)
            coordinates.add(cell)

    def point(self, value, label, walkable=False, bounded=False):
        value = obj(value, label)
        x = integer(value.get("x"), -(2**31), 2**31 - 1, label + ".x")
        y = integer(value.get("y"), -(2**31), 2**31 - 1, label + ".y")
        if (walkable or bounded) and not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError(label + ": point outside map")
        if walkable and self.terrain[y][x] != ".":
            raise ValueError(label + ": point in wall")
        return x, y

    def unit_id(self, value, label):
        value = obj(value, label)
        return (integer(value.get("team_id"), 0, self.players - 1, label + ".team_id"),
                integer(value.get("unit_id"), 0, 2, label + ".unit_id"))

    def site_id(self, value, label):
        value = integer(value, 0, U32, label)
        if value not in self.site_ids:
            raise ValueError(label + ": unknown flag site")
        return value

    def state(self, value, turn, label):
        value = obj(value, label)
        integer(value.get("turn"), turn, turn, label + ".turn")
        scores = array(value.get("scores"), label + ".scores")
        units = array(value.get("units"), label + ".units")
        if len(scores) != self.players or len(units) != self.players * 3:
            raise ValueError(label + ": wrong score/unit count")
        for score in scores:
            integer(score, 0, U32, label + ".scores")
        occupied = set()
        for i, unit in enumerate(units):
            key = f"{label}.units[{i}]"
            unit = obj(unit, key)
            if self.unit_id(unit.get("id"), key + ".id") != (i // 3, i % 3):
                raise ValueError(key + ": unstable unit ID")
            hp = integer(unit.get("hp"), 0, 3, key + ".hp")
            flag_id(unit.get("carrying"), key + ".carrying")
            p = unit.get("position")
            if p is None:
                if hp != 0 or unit.get("carrying") is not None:
                    raise ValueError(key + ": invalid dead unit")
                integer(unit.get("respawn_at_turn"), 1, U32, key + ".respawn_at_turn")
            else:
                cell = self.point(p, key + ".position", walkable=True)
                if hp == 0 or cell in occupied or unit.get("respawn_at_turn") is not None:
                    raise ValueError(key + ": invalid unit occupancy")
                occupied.add(cell)
        flags = array(value.get("flags"), label + ".flags")
        if len(flags) > len(self.site_ids):
            raise ValueError(label + ".flags: too many flags")
        by_id, sources = {}, set()
        for i, flag in enumerate(flags):
            key = f"{label}.flags[{i}]"
            flag = obj(flag, key)
            ident = flag_id(flag.get("id"), key + ".id")
            if ident is None or ident in by_id:
                raise ValueError(key + ": missing/duplicate flag ID")
            site = self.site_id(flag.get("site_id"), key + ".site_id")
            if site in sources:
                raise ValueError(key + ": duplicate source")
            sources.add(site)
            by_id[ident] = flag
            location = obj(flag.get("location"), key + ".location")
            if location.get("state") == "ground":
                self.point(location.get("position"), key + ".location.position", walkable=True)
            elif location.get("state") == "carried":
                team, unit = self.unit_id(location.get("unit"), key + ".location.unit")
                carrier = units[team * 3 + unit]
                if carrier.get("position") is None or carrier.get("carrying") != ident:
                    raise ValueError(key + ": carrier mismatch")
            else:
                raise ValueError(key + ".location.state: unknown state")
        for i, unit in enumerate(units):
            ident = unit.get("carrying")
            if ident is not None and (ident not in by_id or by_id[ident]["location"] != {"state": "carried", "unit": unit["id"]}):
                raise ValueError(f"{label}.units[{i}].carrying: flag mismatch")
        sites = array(value.get("sites"), label + ".sites")
        if len(sites) != len(self.site_ids):
            raise ValueError(label + ".sites: wrong count")
        seen = set()
        for i, site in enumerate(sites):
            key = f"{label}.sites[{i}]"
            site = obj(site, key)
            ident = self.site_id(site.get("site_id"), key + ".site_id")
            if ident in seen:
                raise ValueError(key + ": duplicate site")
            seen.add(ident)
            active = flag_id(site.get("active_flag_id"), key + ".active_flag_id")
            if active is None:
                integer(site.get("next_attempt_turn"), max(1, turn), U32, key + ".next_attempt_turn")
                if ident in sources:
                    raise ValueError(key + ": schedule has active source")
            elif active not in by_id or by_id[active]["site_id"] != ident or site.get("next_attempt_turn") is not None:
                raise ValueError(key + ": source link mismatch")
        if "outcome" not in value:
            raise ValueError(label + ".outcome: missing field")
        outcome = value["outcome"]
        if outcome is not None:
            outcome = obj(outcome, label + ".outcome")
            winners = array(outcome.get("winners"), label + ".outcome.winners")
            for winner in winners:
                integer(winner, 0, self.players - 1, label + ".outcome.winners")
            if winners != [i for i, score in enumerate(scores) if score == max(scores)]:
                raise ValueError(label + ".outcome.winners: differs from scores")
            text(outcome.get("reason"), label + ".outcome.reason")
        if "rng_state" in value:
            value["rng_state"] = str(integer(value["rng_state"], 0, U64, label + ".rng_state"))
        return value

    def event(self, value, label):
        value = obj(value, label)
        kind = text(value.get("type"), label + ".type")
        for field in ("event_id", "phase"):
            text(value.get(field), label + "." + field)
        if kind == "shot":
            self.unit_id(value.get("shooter"), label + ".shooter")
            self.point(value.get("target"), label + ".target")
            for field in ("from", "blocked_by"):
                if value.get(field) is not None:
                    self.point(value[field], label + "." + field, bounded=True)
            if value.get("hit_unit") is not None:
                self.unit_id(value["hit_unit"], label + ".hit_unit")
            text(value.get("validation"), label + ".validation")
            if value.get("result") not in ("hit", "miss", "blocked", "not_executed"):
                raise ValueError(label + ".result: invalid shot result")
            integer(value.get("damage"), 0, 1, label + ".damage")
        if kind in ("hp_change", "death", "move", "carry_change", "score", "respawn", "respawn_blocked", "action_invalid"):
            self.unit_id(value.get("unit"), label + ".unit")
        if kind == "hp_change":
            integer(value.get("before"), 0, 3, label + ".before")
            integer(value.get("after"), 0, 3, label + ".after")
        if kind == "death":
            integer(value.get("respawn_at_turn"), 1, U32, label + ".respawn_at_turn")
        if kind == "move":
            for field in ("from", "target"):
                if value.get(field) is not None:
                    self.point(value[field], label + "." + field)
            text(value.get("result"), label + ".result")
            text(value.get("reason"), label + ".reason")
        if kind == "carry_change":
            flag_id(value.get("before"), label + ".before")
            flag_id(value.get("after"), label + ".after")
            text(value.get("reason"), label + ".reason")
        if kind == "score":
            integer(value.get("team_id"), 0, self.players - 1, label + ".team_id")
            integer(value.get("before"), 0, U32, label + ".before")
            integer(value.get("after"), 0, U32, label + ".after")
        if kind in ("flag_spawned", "flag_spawn_failed", "flag_respawn_scheduled"):
            self.site_id(value.get("site_id"), label + ".site_id")
        if kind == "flag_spawned":
            flag_id(value.get("flag_id"), label + ".flag_id")
            self.point(value.get("position"), label + ".position", walkable=True)
        if kind == "flag_spawn_failed":
            self.unit_id(value.get("occupant"), label + ".occupant")
        if kind == "flag_respawn_scheduled":
            integer(value.get("delay"), 1, 1000000, label + ".delay")
            integer(value.get("next_attempt_turn"), 1, U32, label + ".next_attempt_turn")
