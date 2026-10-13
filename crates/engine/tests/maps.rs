use fff_engine::map::MapDefinition;
use std::path::Path;

fn fixture() -> MapDefinition {
    ron::from_str(include_str!("../../../maps/arena_2p.ron")).unwrap()
}
#[test]
fn all_seven_maps_load_with_their_own_match_limits() {
    let mut previous_limit = 0;
    for players in 2..=8 {
        let path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join(format!("../../maps/arena_{players}p.ron"));
        let map = MapDefinition::load(&path).unwrap();
        assert_eq!(map.players, players);
        assert_eq!(map.match_limits.target_score, 20);
        assert!(map.match_limits.max_turns > previous_limit);
        previous_limit = map.match_limits.max_turns;
    }
}
#[test]
fn default_maps_do_not_give_a_large_head_start_to_the_nearest_flag() {
    use std::collections::{HashSet, VecDeque};
    for players in 2..=8 {
        let path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join(format!("../../maps/arena_{players}p.ron"));
        let map = MapDefinition::load(&path).unwrap();
        let nearest: Vec<_> = map
            .spawn_regions
            .iter()
            .map(|home| {
                let mut queue = VecDeque::new();
                let mut seen = HashSet::new();
                for y in home.y..home.y + 3 {
                    for x in home.x..home.x + 3 {
                        let p = fff_engine::Point::new(x as i32, y as i32);
                        queue.push_back((p, 0));
                        seen.insert((p.x, p.y));
                    }
                }
                while let Some((p, distance)) = queue.pop_front() {
                    if map
                        .flag_points
                        .iter()
                        .any(|f| f.x as i32 == p.x && f.y as i32 == p.y)
                    {
                        return distance;
                    }
                    for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                        let next = fff_engine::Point::new(p.x + dx, p.y + dy);
                        if map.is_walkable(next) && seen.insert((next.x, next.y)) {
                            queue.push_back((next, distance + 1));
                        }
                    }
                }
                panic!("unreachable flags");
            })
            .collect();
        assert!(
            nearest.iter().max().unwrap() - nearest.iter().min().unwrap() <= 1,
            "{players}p nearest-flag head start: {nearest:?}"
        );
    }
}
#[test]
fn broken_border_is_rejected_even_away_from_corners() {
    let mut map = fixture();
    map.terrain[0].replace_range(8..9, ".");
    assert!(map.validate().is_err());
}
#[test]
fn wrong_team_count_and_overlapping_homes_are_rejected() {
    let mut map = fixture();
    map.players = 3;
    assert!(map.validate().is_err());
    let mut map = fixture();
    map.spawn_regions[1].x = map.spawn_regions[0].x;
    map.spawn_regions[1].y = map.spawn_regions[0].y;
    assert!(map.validate().is_err());
}
#[test]
fn duplicate_flag_ids_and_unreachable_floor_are_rejected() {
    let mut map = fixture();
    map.flag_points[1].id = map.flag_points[0].id;
    assert!(map.validate().is_err());
    let mut map = fixture();
    for (x, y) in [(2usize, 1usize), (1, 2), (3, 2), (2, 3)] {
        map.terrain[y].replace_range(x..x + 1, "#");
    }
    assert!(map.validate().is_err());
}
#[test]
fn extreme_dimensions_and_zero_match_limits_are_rejected() {
    let mut map = fixture();
    map.width = u32::MAX;
    assert!(map.validate().is_err());
    let mut map = fixture();
    map.match_limits.max_turns = 0;
    assert!(map.validate().is_err());
    let mut map = fixture();
    map.match_limits.target_score = 0;
    assert!(map.validate().is_err());
}
