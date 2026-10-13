use fff_engine::map::MapDefinition;
use std::path::Path;

fn fixture() -> MapDefinition {
    ron::from_str(include_str!("../../../maps/arena_2p.ron")).unwrap()
}
#[test]
fn all_seven_maps_load_with_their_own_match_limits() {
    for (players, score, turns) in [
        (2, 5, 500),
        (3, 6, 650),
        (4, 6, 650),
        (5, 8, 800),
        (6, 10, 1000),
        (7, 10, 1000),
        (8, 12, 1200),
    ] {
        let path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join(format!("../../maps/arena_{players}p.ron"));
        let map = MapDefinition::load(&path).unwrap();
        assert_eq!(
            (
                map.players,
                map.match_limits.target_score,
                map.match_limits.max_turns
            ),
            (players, score, turns)
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
