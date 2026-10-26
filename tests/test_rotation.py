import random

from rotatarr.config import LibrarySettings, Quota, Settings
from rotatarr.plex import Collection
from rotatarr.plex import Hub
from rotatarr.rotation import build_pool, order_hubs, rotate_library, select, spread
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


def test_pinned_rows_match_identifiers_without_hub_prefix():
    # Plex names many built-in rows "movie.recentlyreleased", without "hub.".
    plex = FakePlex(make_collections(10), builtin=("movie.recentlyreleased", "movie.recentlyadded",
                                                   "hub.movie.topunwatched"))
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
    settings = Settings(pinned_rows=["recentlyreleased", "recentlyadded"])
    for seed in range(5):
        rotate_library(plex, "1", "Movies", lib, settings, random.Random(seed))
        order = [h.identifier for h in plex.hub_list]
        assert order[:2] == ["movie.recentlyreleased", "movie.recentlyadded"]


def test_pinned_rows_are_shown_everywhere():
    plex = FakePlex(make_collections(10))
    for h in plex.hub_list:
        h.home = h.shared = False
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
    rotate_library(plex, "1", "Movies", lib, Settings(pinned_rows=["recentlyadded"]), random.Random(0))
    flags = {h.identifier: (h.recommended, h.home, h.shared) for h in plex.hub_list}
    assert flags["hub.movie.recentlyadded"] == (True, True, True)
    assert flags["hub.movie.topunwatched"] == (True, False, False)  # not pinned: left alone


def test_pinned_rows_come_back_to_recommended():
    plex = FakePlex(make_collections(10))
    row = next(h for h in plex.hub_list if h.identifier == "hub.movie.recentlyadded")
    row.recommended = row.home = False
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
    settings = Settings(pinned_rows=["recentlyadded"], pinned_home=False, pinned_shared=True)
    rotate_library(plex, "1", "Movies", lib, settings, random.Random(0))
    assert (row.recommended, row.home, row.shared) == (True, False, True)


def test_pinned_rows_home_and_friends_are_separate():
    plex = FakePlex(make_collections(10))
    for h in plex.hub_list:
        h.home = h.shared = False
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
    settings = Settings(pinned_rows=["recentlyadded"], pinned_home=True, pinned_shared=False)
    rotate_library(plex, "1", "Movies", lib, settings, random.Random(0))
    h = next(h for h in plex.hub_list if h.identifier == "hub.movie.recentlyadded")
    assert (h.recommended, h.home, h.shared) == (True, True, False)


def test_pinned_rows_go_on_top_without_shuffling():
    plex = FakePlex(make_collections(10))
    plex.move_hub(None, "hub.movie.recentlyadded", plex.hub_list[-1].identifier)
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5, shuffle_order=False)
    rotate_library(plex, "1", "Movies", lib, Settings(pinned_rows=["recentlyadded"]), random.Random(0))
    assert plex.hub_list[0].identifier == "hub.movie.recentlyadded"


class TopMoveIgnored(FakePlex):
    """A Plex that ignores moves to the top."""

    def move_hub(self, sid, ident, after):
        if after is not None:
            super().move_hub(sid, ident, after)


def test_pinned_rows_reach_the_top_when_plex_ignores_moves_to_the_top():
    plex = TopMoveIgnored(make_collections(10))
    plex.hub_list.insert(0, Hub("custom.collection.1.999", "Hidden", False, False, False))
    FakePlex.move_hub(plex, None, "hub.movie.recentlyadded", plex.hub_list[-1].identifier)
    for shuffle in (True, False):
        lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5, shuffle_order=shuffle)
        rotate_library(plex, "1", "Movies", lib, Settings(pinned_rows=["recentlyadded"]), random.Random(0))
        assert plex.hub_list[0].identifier == "hub.movie.recentlyadded"


class AfterIgnored(FakePlex):
    """A Plex that ignores "after" and moves every row to the top."""

    def move_hub(self, sid, ident, after):
        super().move_hub(sid, ident, None)


class MovesBefore(FakePlex):
    """A Plex that puts a row before the "after" row instead of behind it."""

    def move_hub(self, sid, ident, after):
        self.calls.append(("move", ident))
        h = self._hub(ident)
        self.hub_list.remove(h)
        pos = 0 if after is None else self.hub_list.index(self._hub(after))
        self.hub_list.insert(pos, h)


def test_order_holds_when_plex_reads_after_differently():
    for cls in (AfterIgnored, MovesBefore):
        plex = cls(make_collections(10))
        lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
        settings = Settings(pinned_rows=["recentlyadded", "inprogress"])
        for seed in range(3):
            rotate_library(plex, "1", "Movies", lib, settings, random.Random(seed))
            order = [h.identifier for h in plex.hub_list]
            assert order[:2] == ["hub.movie.recentlyadded", "hub.movie.inprogress"], cls.__name__


class MovesIgnored(FakePlex):
    """A Plex that answers moves with OK but never changes the order."""

    def move_hub(self, sid, ident, after):
        self.calls.append(("move", ident))


def test_no_second_round_of_moves_when_plex_ignores_them():
    plex = MovesIgnored(make_collections(10))
    lib = LibrarySettings(enabled=True, recommended=5, home=5, shared=5)
    rotate_library(plex, "1", "Movies", lib, Settings(pinned_rows=["recentlyadded"]), random.Random(0))
    moves = [c for c in plex.calls if c[0] == "move"]
    assert len(moves) == len([h for h in plex.hub_list if h.visible])


def test_spread_keeps_similar_rows_apart():
    ids = [f"a{i}" for i in range(10)] + [f"b{i}" for i in range(10)] + [f"c{i}" for i in range(5)]
    kinds = {i: i[0] for i in ids}
    for seed in range(20):
        order = spread(ids, kinds, random.Random(seed))
        assert sorted(order) == sorted(ids)
        assert all(kinds[x] != kinds[y] for x, y in zip(order, order[1:]))


def test_order_spreads_series_and_name_groups():
    hubs = [Hub(f"custom.collection.1.{i}", f"Best of {1950 + 10 * i}s", True, False, False) for i in range(5)]
    hubs += [Hub(f"custom.collection.1.{10 + i}", f"Saga {i}", True, False, False) for i in range(5)]
    hubs += [Hub(f"custom.collection.1.{20 + i}", f"Genre {i}", True, False, False) for i in range(10)]
    automatic = {str(10 + i) for i in range(5)}
    titles = {h.identifier: h for h in hubs}
    for seed in range(20):
        order = order_hubs(hubs, {}, [], random.Random(seed), automatic)
        kinds = ["auto" if titles[i].collection_key in automatic else titles[i].title.split()[0] for i in order]
        assert not any(a == b and a != "Genre" for a, b in zip(kinds, kinds[1:]))


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


def test_automatic_collections_are_limited():
    pool = [Collection(str(i), f"Series {i}", 5, False, automatic=True) for i in range(10)]
    pool += [Collection(str(100 + i), f"Mine {i}", 5, False) for i in range(10)]
    lib = LibrarySettings(recommended=8, home=8, shared=8, automatic_max=2)
    picked = select(pool, lib, random.Random(1))
    assert len(picked) == 8
    assert sum(c.automatic for c in picked) == 2


def test_bare_number_quota_from_old_versions_is_dropped():
    lib = LibrarySettings.model_validate({"quotas": [{"match": "10", "max": 0}, {"match": "Best of", "max": 3}]})
    assert [q.match for q in lib.quotas] == ["Best of"]


def test_exclude_supports_patterns():
    cols = [Collection("1", "Best of 1930s", 10, False), Collection("2", "Best of 1990s", 10, False),
            Collection("3", "Lowest Rated", 10, False)]
    lib = LibrarySettings(exclude=["/^Best of 19[3-6]0s$/", "lowest"])
    assert [c.title for c in build_pool(cols, lib)] == ["Best of 1990s"]


def test_invalid_pattern_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        LibrarySettings(exclude=["/[unclosed/"])


def test_home_screens_get_their_own_limit_for_automatic_collections():
    from rotatarr.rotation import placements, rank_for_home
    pool = [Collection(str(i), f"Series {i}", 5, False, automatic=True) for i in range(30)]
    pool += [Collection(str(100 + i), f"Mine {i}", 5, False) for i in range(20)]
    lib = LibrarySettings(recommended=40, home=10, shared=10, automatic_max_home=2)
    selection = rank_for_home(select(pool, lib, random.Random(3)), lib)
    placed = placements(selection, lib)
    home = [c for c in selection if placed[c.rating_key].home]
    assert len(home) == 10
    assert sum(c.automatic for c in home) == 2
    assert sum(placed[c.rating_key].recommended for c in selection) == 40
