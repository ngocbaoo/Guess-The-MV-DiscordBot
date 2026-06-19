"""GameSession: first-correct-wins, race/idempotency, stage points, skip vote.

Timeline management is disabled (manage_timeline=False) so we drive transitions
explicitly and assert the lock + round_ended flag prevent double awards. Each
scenario runs inside a single event loop via asyncio.run."""
import asyncio

from bot.game import GameSession, Presenter, Question

FRAMES = [{"file_path": "x", "openness": "normal"}] * 3


class FakePresenter(Presenter):
    def __init__(self):
        self.events = []

    async def show_question(self, s, q):
        self.events.append(("show", q.song["id"]))

    async def update_stage(self, s, q, stage):
        self.events.append(("stage", stage))

    async def reveal(self, s, q, winner, points, reason):
        self.events.append(("reveal", reason, winner, points))

    async def game_over(self, s):
        self.events.append(("over",))


def _typing_question(aliases=("chay ngay di",), title="Chay Ngay Di"):
    return Question(song={"id": 1, "title": title, "artist": "ST", "url": ""},
                    aliases_norm=list(aliases), frames=FRAMES, seed=1)


def _session(questions, mode="typing"):
    return GameSession(None, "g", "c", mode, questions, FakePresenter(),
                       clock=lambda: 0.0, reveal_pause=0.0,
                       scoring_enabled=False, manage_timeline=False)


def test_first_correct_wins_and_no_double_award():
    async def scenario():
        s = _session([_typing_question()])
        await s.start()
        assert await s.submit_typing("u1", "Chạy Ngay Đi") is True
        assert s.scores["u1"] == 5                       # stage 0 -> 5 points
        # Round is closed: later guesses and the timeout are no-ops.
        assert await s.submit_typing("u2", "chay ngay di") is None
        await s.timeout_now()
        assert dict(s.scores) == {"u1": 5}
        assert "u2" not in s.scores
        assert s.round_ended is True
    asyncio.run(scenario())


def test_points_follow_current_stage():
    async def scenario():
        s = _session([_typing_question()])
        await s.start()
        await s.advance_stage_to(2)                       # typing stage 2 -> 3 pts
        assert await s.submit_typing("u1", "chay ngay di") is True
        assert s.scores["u1"] == 3
    asyncio.run(scenario())


def test_wrong_guess_marks_active_but_no_points():
    async def scenario():
        s = _session([_typing_question()])
        await s.start()
        assert await s.submit_typing("u1", "totally wrong") is False
        assert "u1" in s.answered_active
        assert "u1" not in s.scores
        assert s.round_ended is False
    asyncio.run(scenario())


def test_skip_needs_majority_of_active_players():
    async def scenario():
        s = _session([_typing_question(), _typing_question()])
        await s.start()
        await s.submit_typing("u1", "wrong")
        await s.submit_typing("u2", "wrong")             # active = {u1, u2}
        assert await s.vote_skip("u1") == "voted"        # 1 of 2 not majority
        assert await s.vote_skip("u1") == "already"      # no re-vote
        assert await s.vote_skip("u2") == "skipped"      # 2 of 2 -> skip
        assert s.round_ended is True
        assert 1 in s.skipped_song_ids
    asyncio.run(scenario())


def test_mc_match_by_id():
    async def scenario():
        q = Question(song={"id": 42, "title": "Ans", "artist": "", "url": ""},
                     aliases_norm=[], frames=FRAMES, seed=1,
                     mc_options=[{"id": 42, "title": "Ans"},
                                 {"id": 7, "title": "Other"}])
        s = _session([q], mode="mc")
        await s.start()
        assert await s.submit_mc("u1", 7) is False       # wrong button
        assert await s.submit_mc("u1", 42) is True        # correct id
        assert s.scores["u1"] == 5
    asyncio.run(scenario())
