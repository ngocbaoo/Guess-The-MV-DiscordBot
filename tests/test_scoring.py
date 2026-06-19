"""Scores: atomic accumulating UPSERT across 'all' + weekly periods."""
import datetime

from bot import scoring

NOW = datetime.datetime(2026, 6, 19, tzinfo=datetime.timezone.utc)


def test_upsert_accumulates_points_and_keeps_fastest(db_factory):
    conn = db_factory([])
    scoring.record_correct(conn, "g", "u", 5, time_ms=1200, now=NOW)
    scoring.record_correct(conn, "g", "u", 3, time_ms=800, now=NOW)

    rows = {r["period"]: r for r in conn.execute(
        "SELECT * FROM scores WHERE guild_id='g' AND user_id='u'")}
    wk = scoring.week_key(NOW)
    assert set(rows) == {"all", wk}
    assert rows["all"]["points"] == 8
    assert rows["all"]["correct_count"] == 2
    assert rows["all"]["fastest_ms"] == 800        # min of 1200, 800
    assert rows[wk]["points"] == 8


def test_top_scores_orders_by_points_then_speed(db_factory):
    conn = db_factory([])
    scoring.record_correct(conn, "g", "slow", 5, time_ms=5000, now=NOW)
    scoring.record_correct(conn, "g", "fast", 5, time_ms=1000, now=NOW)
    scoring.record_correct(conn, "g", "low", 1, time_ms=10, now=NOW)

    top = scoring.top_scores(conn, "g", "all", limit=10)
    assert [r["user_id"] for r in top] == ["fast", "slow", "low"]
