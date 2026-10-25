import random

from rotatarr.config import LibrarySettings, Quota, Settings
from rotatarr.plex import Collection
from rotatarr.rotation import build_pool, rotate_library, select
from rotatarr.shuffle import shuffle_library

from .fakeplex import FakePlex, make_collections


def visible_collection_hubs(plex):
    return [h for h in plex.hub_list if h.collection_key and h.visible]


def test_pool_drops_small_and_excluded():
    cols = [Collection("1", "Big", 10, False), Collection("2", "Tiny", 1, False),
            Collection("3", "Lowest Rated", 10, False)]
    lib = LibrarySettings(min_items=3, exclude=["lowest rated"])
    assert [c.title for c in build_pool(cols, lib)] == ["Big"]


def test_select_respects_quota_and_always_visible():
    cols = make_collections(20, "Saga") + make_collections(20, "Genre", start=200)
    lib = LibrarySettings(recommended=15, home=5, shared=5, quotas=[Quota(match="saga", max=3)],
                          always_visible=["Genre 7"])
    chosen = select(cols, lib, random.Random(1))
    assert len(chosen) == 15
    assert chosen[0].title == "Genre 7"
    assert sum("Saga" in c.title for c in chosen) <= 3


def test_rotation_sets_nested_visibility():
    plex = FakePlex(make_collections(30))
    lib = LibrarySettings(enabled=True, recommended=12, home=4, shared=2)
    rotate_library(plex, "1", "Movies", lib, Settings(), random.Random(2))
    hubs = visible_collection_hubs(plex)
    assert len(hubs) == 12
    assert sum(h.recommended for h in hubs) == 12
    assert sum(h.home for h in hubs) == 4
    assert sum(h.shared for h in hubs) == 2


def test_rotation_hides_previous_selection():
    plex = FakePlex(make_collections(30))
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
    for seed in range(5):
        rotate_library(plex, "1", "Movies", lib, Settings(), random.Random(seed))
        assert len(visible_collection_hubs(plex)) == 5


def test_pinned_builtin_rows_stay_on_top():
    plex = FakePlex(make_collections(10))
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
    settings = Settings(pinned_rows=["inprogress", "recentlyadded"])
    for seed in range(5):
        rotate_library(plex, "1", "Movies", lib, settings, random.Random(seed))
        order = [h.identifier for h in plex.hub_list]
        assert order[:2] == ["hub.movie.inprogress", "hub.movie.recentlyadded"]
        # every visible row comes before every hidden row
        flags = [h.visible for h in plex.hub_list]
        assert flags == sorted(flags, reverse=True)


def test_dry_run_changes_nothing():
    plex = FakePlex(make_collections(10))
    lib = LibrarySettings(enabled=True, recommended=5, home=0, shared=0)
    result = rotate_library(plex, "1", "Movies", lib, Settings(dry_run=True), random.Random(0))
    assert plex.calls == []
    assert result.changed == 5


def test_shuffle_skips_smart_and_hidden_collections():
    cols = make_collections(3) + make_collections(2, "Smart", start=300, smart=True)
    plex = FakePlex(cols)
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
    rotate_library(plex, "1", "Movies", lib, Settings(), random.Random(0))
    result = shuffle_library(plex, "1", "Movies", Settings(items_to_front=4), random.Random(0))
    assert result.shuffled == 3
    assert result.smart_skipped == 2
    assert all(plex.sorts[c.rating_key] == "2" for c in cols[:3])


def test_never_list_matches_exact_title_only():
    cols = [Collection("1", "Matrix", 10, False), Collection("2", "Matrix Reloaded", 10, False)]
    lib = LibrarySettings(never=["matrix"])
    assert [c.title for c in build_pool(cols, lib)] == ["Matrix Reloaded"]


def test_seasonal_collection_only_in_season():
    from datetime import date
    from rotatarr.config import Seasonal
    cols = make_collections(5) + [Collection("900", "Halloween", 20, False), Collection("901", "Christmas", 20, False)]
    lib = LibrarySettings(recommended=3, home=0, shared=0, seasonal=[
        Seasonal(title="Halloween", start="10-01", end="10-31"),
        Seasonal(title="Christmas", start="12-01", end="01-06"),
    ])
    october = build_pool(cols, lib, date(2026, 10, 25))
    assert "Halloween" in [c.title for c in october] and "Christmas" not in [c.title for c in october]
    assert select(october, lib, random.Random(0))[0].title == "Halloween"
    january = [c.title for c in build_pool(cols, lib, date(2027, 1, 3))]
    assert "Christmas" in january and "Halloween" not in january


def test_recent_collections_are_used_last():
    cols = make_collections(10)
    lib = LibrarySettings(recommended=5, home=0, shared=0)
    recent = {c.rating_key for c in cols[:5]}
    chosen = select(cols, lib, random.Random(0), recent)
    assert not recent & {c.rating_key for c in chosen}
    # with too few fresh collections the recent ones fill up
    lib.recommended = 8
    assert len(select(cols, lib, random.Random(0), recent)) == 8


def test_reset_restores_rows_and_sorts():
    from rotatarr import state
    from rotatarr.rotation import restore_library
    plex = FakePlex(make_collections(10))
    before = [(h.identifier, h.visible) for h in plex.hub_list]
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
    rotate_library(plex, "1", "Movies", lib, Settings(), random.Random(1))
    shuffle_library(plex, "1", "Movies", Settings(), random.Random(1))
    rotate_library(plex, "1", "Movies", lib, Settings(), random.Random(2))
    assert plex.sorts

    restore_library(plex, "1", state.snapshot()["1"])
    after = [(h.identifier, h.visible) for h in plex.hub_list if h.visible]
    assert after == [b for b in before if b[1]]
    assert set(plex.sorts.values()) == {"0"}
