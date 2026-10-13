import copy
import json
from pathlib import Path
import tempfile
import unittest
import export

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fff-viewer-")
        self.root = Path(self.temp.name) / "match"
        self.root.mkdir()
        (self.root / "frames").mkdir()
        teams = [{"team_id": i, "name": "bot </script><script>alert(1)</script>"} for i in range(2)]
        self.manifest = {"format_version": 1, "match_id": "test", "status": "complete", "last_complete_turn": 1,
                         "seed": 18446744073709551615, "teams": teams}
        grid = ["#########"] + ["#.......#"] * 7 + ["#########"]
        self.map = {"format_version": 1, "id": "test", "players": 2, "width": 9, "height": 9, "terrain": grid,
                    "match_limits": {"target_score": 5, "max_turns": 100},
                    "spawn_regions": [{"team_id": 0, "x": 1, "y": 1, "width": 3, "height": 3},
                                      {"team_id": 1, "x": 5, "y": 5, "width": 3, "height": 3}],
                    "flag_points": [{"id": 0, "x": 4, "y": 4}]}
        positions = [(1, 1), (2, 1), (3, 1), (5, 5), (6, 5), (7, 5)]
        units = [{"id": {"team_id": i // 3, "unit_id": i % 3}, "position": {"x": x, "y": y}, "hp": 3,
                  "carrying": None, "respawn_at_turn": None} for i, (x, y) in enumerate(positions)]
        self.state = {"turn": 0, "scores": [0, 0], "units": units,
                      "flags": [{"id": 1, "site_id": 0, "location": {"state": "ground", "position": {"x": 4, "y": 4}}}],
                      "sites": [{"site_id": 0, "active_flag_id": 1, "next_attempt_turn": None}],
                      "rng_state": 18446744073709551615, "next_flag_id": 2, "outcome": None}
        start = copy.deepcopy(self.state)
        start["turn"] = 1
        end = copy.deepcopy(start)
        end["outcome"] = {"winners": [0, 1], "reason": "max_turns"}
        calls = [{"team_id": i, "turn": 1, "status": "ok", "elapsed_us": 100, "init_elapsed_us": 0, "error": None} for i in range(2)]
        self.record = {"format_version": 1, "call_order": [0, 1], "calls": calls,
                       "frame": {"turn": 1, "start": start, "end": end, "events": []}}
        self.write("manifest.json", self.manifest)
        self.write("map.json", self.map)
        self.write("initial.json", {"format_version": 1, "state": self.state})
        self.write("frames/000001.json", self.record)
        self.write("summary.json", {"complete": True, "turns": 1, "scores": [0, 0]})
    def tearDown(self):
        self.temp.cleanup()
    def write(self, path, value):
        (self.root / path).write_text(json.dumps(value), encoding="utf-8")
    def test_export_is_offline_escapes_script_and_preserves_large_seed(self):
        output = Path(self.temp.name) / "replay.html"
        export.export(self.root, output)
        html = output.read_text()
        self.assertNotIn("bot </script><script>", html)
        self.assertIn(r"\u003c/script\u003e", html)
        self.assertIn('"18446744073709551615"', html)
        self.assertNotIn("__REPLAY_DATA__", html)
        self.assertNotIn('<script src="http', html)
        data = export.load_replay(self.root)
        self.assertEqual(len(data["records"]), 1)
        self.assertEqual(data["initial"]["turn"], 0)
    def test_unknown_version_and_missing_frame_are_diagnosed(self):
        self.manifest["format_version"] = 999
        self.write("manifest.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "version|版本"):
            export.load_replay(self.root)
        self.manifest["format_version"] = 1
        self.write("manifest.json", self.manifest)
        (self.root / "frames/000001.json").unlink()
        with self.assertRaisesRegex(ValueError, "000001"):
            export.load_replay(self.root)
    def test_path_escape_and_duplicate_unit_positions_are_rejected(self):
        (self.root / "map.json").unlink()
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text(json.dumps(self.map))
        (self.root / "map.json").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "escape|越界|目录"):
            export.load_replay(self.root)
        (self.root / "map.json").unlink()
        self.write("map.json", self.map)
        self.record["frame"]["end"]["units"][1]["position"] = self.record["frame"]["end"]["units"][0]["position"]
        self.write("frames/000001.json", self.record)
        with self.assertRaisesRegex(ValueError, "unit|棋子|占格"):
            export.load_replay(self.root)
    def test_player_consumed_nested_shapes_are_rejected_with_field_paths(self):
        mutations = [
            ("initial.json", ("state", "sites"), None),
            ("initial.json", ("state", "outcome"), {"winners": None, "reason": "max_turns"}),
            ("initial.json", ("state", "units", 0), None),
            ("map.json", ("spawn_regions", 0), None),
            ("map.json", ("flag_points", 0, "x"), "bad"),
            ("frames/000001.json", ("frame", "events"), [None]),
            ("frames/000001.json", ("frame", "events"), [{"event_id": "x", "phase": "shoot", "type": "shot", "shooter": None}]),
            ("frames/000001.json", ("calls", 0), None),
        ]
        for filename, fields, bad in mutations:
            with self.subTest(filename=filename, fields=fields):
                path = self.root / filename
                original = path.read_text()
                value = json.loads(original)
                nested = value
                for field in fields[:-1]:
                    nested = nested[field]
                nested[fields[-1]] = bad
                self.write(filename, value)
                try:
                    with self.assertRaises(ValueError) as caught:
                        export.load_replay(self.root)
                    self.assertIn(filename, str(caught.exception))
                finally:
                    path.write_text(original)

    def test_incomplete_prefix_does_not_require_summary(self):
        self.manifest["status"] = "in_progress"
        self.write("manifest.json", self.manifest)
        (self.root / "summary.json").unlink()
        self.assertIsNone(export.load_replay(self.root)["summary"])

if __name__ == "__main__":
    unittest.main()
