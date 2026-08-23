from danmakufuzz.semantic.basin_harvest import ScalarHotspot, _neighbor_values, _spread_sample


def test_spread_sample_keeps_extremes_and_middle() -> None:
    values = [1, 8, 64, 248, 4096]
    assert _spread_sample(values, 3) == [1, 64, 4096]


def test_neighbor_values_picks_closest_boundaries() -> None:
    interesting = [-1, 0, 2147483602]
    noninteresting = [64, 112, 184, 248, 2168]
    assert _neighbor_values(interesting, noninteresting, 4) == [64, 2168]


def test_scalar_hotspot_selected_values_combines_interesting_and_neighbors() -> None:
    hotspot = ScalarHotspot(
        stage=1,
        seed_name="ecldata1.ecl",
        family="shoot-interval",
        sub_index=0,
        instruction_index=7,
        field_offset=0,
        field_name="time",
    )
    hotspot.values_interesting.extend([-1, 0, 2147483602])
    hotspot.values_total.extend([-1, 0, 64, 112, 184, 248, 2168, 2147483602])
    assert hotspot.selected_values(
        max_interesting_values=8,
        max_neighbor_values=4,
        sentinel_values=[-1, 0, 1],
    ) == [-1, 0, 1, 64, 2168, 2147483602]
