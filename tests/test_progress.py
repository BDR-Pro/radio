from sdr_kid import progress


def test_first_plane_unlocks():
    unlocked = progress.record("plane_seen")
    keys = {q.key for q in unlocked}
    assert "first_plane" in keys


def test_five_planes_unlocks_after_five():
    for _ in range(4):
        progress.record("plane_seen")
    assert not any(q.key == "five_planes" for q in progress.record("plane_seen", amount=0))
    unlocked = progress.record("plane_seen")  # -> 5
    assert any(q.key == "five_planes" for q in unlocked)


def test_unlocked_once():
    progress.record("iss_map_opened")
    second = progress.record("iss_map_opened")
    assert not any(q.key == "iss_map" for q in second)


def test_summary_table_has_rows():
    progress.record("plane_seen")
    table = progress.summary_table()
    assert len(table.rows) == len(progress.QUESTS)
