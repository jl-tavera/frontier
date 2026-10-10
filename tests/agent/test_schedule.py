import pytest

from app.agent.loop import schedule
from app.agent.parse import Query


def qs(*spec):
    return [Query(op, entity) for op, entity in (s.split() for s in spec)]


@pytest.mark.parametrize("spec, hits, order", [
    (["read A", "create B", "read A"], {"A"}, [0, 2, 1]),  # cache answers first
    (["read A", "read B", "read A"], set(), [0, 2, 1]),  # one go_to per entity
    (["update A", "read A"], {"A"}, [0, 1]),  # a read after a write sees it
    (["read A", "update A", "read A", "read B"], {"A", "B"}, [0, 3, 1, 2]),
    (["read A"], set(), [0]),
    (["read A", "update A"], {"A"}, [0, 1]),
])
def test_schedule(spec, hits, order):
    assert schedule(qs(*spec), hits) == order
