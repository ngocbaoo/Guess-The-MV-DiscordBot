"""Persistent scores: atomic UPSERT + leaderboard reads.

We use an accumulating UPSERT (not read-modify-write) so concurrent channels in
the same guild can't clobber each other. Each correct answer bumps two periods
-- 'all' and the current ISO week -- inside ONE transaction.
"""
import datetime

_UPSERT = """
INSERT INTO scores (guild_id, user_id, period, points, correct_count, fastest_ms)
VALUES (:guild_id, :user_id, :period, :points, 1, :time_ms)
ON CONFLICT(guild_id, user_id, period) DO UPDATE SET
  points        = points + :points,
  correct_count = correct_count + 1,
  fastest_ms    = MIN(COALESCE(fastest_ms, :time_ms), COALESCE(:time_ms, fastest_ms))
"""


def week_key(now: datetime.datetime = None) -> str:
    """ISO week key 'YYYY-Www' (UTC)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def record_correct(conn, guild_id, user_id, points, time_ms=None,
                   now: datetime.datetime = None) -> None:
    """Add `points` (and one correct) to both 'all' and the weekly period."""
    periods = ("all", week_key(now))
    with conn:  # single transaction across both periods
        for period in periods:
            conn.execute(_UPSERT, {
                "guild_id": str(guild_id),
                "user_id": str(user_id),
                "period": period,
                "points": points,
                "time_ms": time_ms,
            })


def top_scores(conn, guild_id, period="all", limit=10):
    """Leaderboard rows for a guild+period, best first (points, then fastest)."""
    return conn.execute(
        "SELECT user_id, points, correct_count, fastest_ms FROM scores "
        "WHERE guild_id = ? AND period = ? "
        "ORDER BY points DESC, fastest_ms IS NULL, fastest_ms ASC "
        "LIMIT ?",
        (str(guild_id), period, limit),
    ).fetchall()
