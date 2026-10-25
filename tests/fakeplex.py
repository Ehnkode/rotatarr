"""In-memory stand-in for PlexClient, recording every change."""

from rotatarr.plex import Collection, Hub


class FakePlex:
    def __init__(self, collections, builtin=("hub.movie.inprogress", "hub.movie.recentlyadded",
                                             "hub.movie.topunwatched")):
        self.sid = "1"
        self._collections = collections
        self.items = {c.rating_key: [f"{c.rating_key}-{i}" for i in range(c.child_count)] for c in collections}
        self.sorts = {}
        self.hub_list = [Hub(b, b, True, True, True) for b in builtin]
        self.calls = []

    # read
    def sections(self):
        return [{"key": self.sid, "title": "Movies", "type": "movie"}]

    def collections(self, sid):
        return list(self._collections)

    def hubs(self, sid):
        return [Hub(h.identifier, h.title, h.recommended, h.home, h.shared) for h in self.hub_list]

    def collection_meta(self, key):
        c = next(c for c in self._collections if c.rating_key == key)
        return {"smart": "1" if c.smart else "0", "collectionSort": self.sorts.get(key, "0")}

    def collection_items(self, key):
        return list(self.items[key])

    # write
    def _hub(self, ident):
        return next(h for h in self.hub_list if h.identifier == ident)

    def set_visibility(self, sid, ident, rec, home, shared):
        self.calls.append(("visibility", ident))
        h = self._hub(ident)
        h.recommended, h.home, h.shared = rec, home, shared

    def create_collection_hub(self, sid, key, rec, home, shared):
        self.calls.append(("create", key))
        title = next(c.title for c in self._collections if c.rating_key == key)
        self.hub_list.append(Hub(f"custom.collection.{sid}.{key}", title, rec, home, shared))

    def move_hub(self, sid, ident, after):
        self.calls.append(("move", ident))
        h = self._hub(ident)
        self.hub_list.remove(h)
        pos = 0 if after is None else self.hub_list.index(self._hub(after)) + 1
        self.hub_list.insert(pos, h)

    def set_custom_sort(self, key):
        self.set_sort(key, "2")

    def set_sort(self, key, sort):
        self.sorts[key] = sort

    def move_item(self, key, item, after):
        self.calls.append(("move_item", key))
        items = self.items[key]
        items.remove(item)
        items.insert(0 if after is None else items.index(after) + 1, item)


def make_collections(n, prefix="Collection", start=100, items=10, smart=False):
    return [Collection(str(start + i), f"{prefix} {i}", items, smart) for i in range(n)]
