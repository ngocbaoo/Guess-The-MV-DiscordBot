"""Per-channel game session: state machine + scheduler.

This is the race-prone heart of the bot, so the rules are strict:

* Every question is SNAPSHOTTED at start (3 frames, masking seed, MC option
  order). Nothing is re-queried mid-question.
* All state changes for a question go through methods guarded by ONE asyncio
  lock, plus an idempotent `round_ended` flag. The timer never mutates state on
  its own -- it calls the same guarded methods. So a correct guess racing the
  stage timer can never award twice or advance a closed round.
* Every way a round can end (correct / timeout / skip) cancels the pending
  timeline task.

GameSession is framework-agnostic: I/O happens through an injected `presenter`
and time through an injected `clock`, so the logic is testable without Discord.
"""
import asyncio
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field

from bot.choices import build_choices
from bot.config import (END_MC, END_TYPING, POINTS_MC, POINTS_TYPING, STEPS_MC,
                        STEPS_TYPING)
from bot.matching import is_correct_mc, is_correct_typing
from bot.selection import load_aliases_norm, load_frames, order_frames


@dataclass
class Question:
    """Immutable snapshot of one question, fixed at game start."""
    song: dict                       # id, title, artist, url, ...
    aliases_norm: list               # normalized aliases for typing match
    frames: list                     # 3 ordered {file_path, openness} (hard/med/easy)
    seed: int                        # stable masking seed for this question
    mc_options: list = None          # [{id,title}] for MC mode, else None


def build_questions(conn, chosen, pool, mode, rng=random):
    """Turn the chosen song rows into fully-snapshotted Question objects.

    For MC, distractors avoid every answer in the game (no cross-question
    spoilers); the choices fallback chain handles a thin pool.
    """
    answer_ids = {s["id"] for s in chosen}
    questions = []
    for song in chosen:
        frames = order_frames(load_frames(conn, song["id"]), rng)
        aliases = load_aliases_norm(conn, song["id"])
        mc_options = None
        if mode == "mc":
            exclude = answer_ids - {song["id"]}
            mc_options = build_choices(conn, song, pool, exclude, rng)
        questions.append(Question(
            song=dict(song), aliases_norm=aliases, frames=frames,
            seed=rng.getrandbits(32), mc_options=mc_options,
        ))
    return questions


class Presenter:
    """I/O hooks. Discord implementation lives in bot.py; tests use a fake."""

    async def show_question(self, session, q):
        ...

    async def update_stage(self, session, q, stage):
        ...

    async def reveal(self, session, q, winner, points, reason):
        ...

    async def game_over(self, session):
        ...


class GameSession:
    def __init__(self, conn, guild_id, channel_id, mode, questions, presenter,
                 *, clock=time.monotonic, reveal_pause=4.0,
                 scoring_enabled=True, manage_timeline=True):
        self.conn = conn
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.mode = mode                      # 'typing' | 'mc'
        self.questions = questions
        self.presenter = presenter
        self.clock = clock
        self.reveal_pause = reveal_pause
        self.scoring_enabled = scoring_enabled
        self.manage_timeline = manage_timeline

        self.steps = STEPS_TYPING if mode == "typing" else STEPS_MC
        self.points = POINTS_TYPING if mode == "typing" else POINTS_MC
        self.end_sec = END_TYPING if mode == "typing" else END_MC

        self.lock = asyncio.Lock()
        self.idx = -1
        self.stage = 0
        self.round_ended = True               # no live round until first question
        self.finished = False
        self.q_start = 0.0
        self.answered_active = set()           # users who guessed >=1 this question
        self.skip_votes = set()
        self.scores = defaultdict(int)         # in-memory game scoreboard
        self.fastest = {}                      # user -> fastest correct ms (this game)
        self.skipped_song_ids = set()
        self._timeline_task = None
        self._advance_task = None

    # ---- lifecycle ----------------------------------------------------------
    async def start(self):
        await self._start_question(0)

    @property
    def current(self):
        return self.questions[self.idx]

    async def _start_question(self, idx):
        async with self.lock:
            self.idx = idx
            self.stage = 0
            self.round_ended = False
            self.q_start = self.clock()
            self.answered_active = set()
            self.skip_votes = set()
            q = self.questions[idx]
        await self.presenter.show_question(self, q)
        if self.manage_timeline:
            self._timeline_task = asyncio.create_task(self._run_timeline())

    async def _run_timeline(self):
        """Sleep through the checkpoints, advancing the stage at each, then end
        on timeout. Cancelled when the round ends early."""
        try:
            prev = self.steps[0]
            for stage, sec in enumerate(self.steps[1:], start=1):
                await asyncio.sleep(sec - prev)
                prev = sec
                await self.advance_stage_to(stage)
            await asyncio.sleep(self.end_sec - prev)
            await self.timeout_now()
        except asyncio.CancelledError:
            return

    # ---- the single guarded state-transition surface ------------------------
    async def advance_stage_to(self, stage):
        """Move to a later stage (image + hint). No-op if the round is closed."""
        async with self.lock:
            if self.round_ended:
                return
            self.stage = stage
            q = self.current
        await self.presenter.update_stage(self, q, stage)

    async def timeout_now(self):
        """End the round with no winner (time ran out)."""
        async with self.lock:
            if self.round_ended:
                return
            await self._end_round(winner=None, points=0, reason="timeout")

    async def submit_typing(self, user_id, guess):
        """Typing guess. Returns True if correct (round closed), False if wrong,
        None if there is no live round."""
        async with self.lock:
            if self.round_ended:
                return None
            self.answered_active.add(user_id)
            ok, _score = is_correct_typing(guess, self.current.aliases_norm)
            if not ok:
                return False
            await self._award_and_end(user_id)
            return True

    async def submit_mc(self, user_id, picked_song_id):
        """MC button press, matched by song_id. Same return contract."""
        async with self.lock:
            if self.round_ended:
                return None
            self.answered_active.add(user_id)
            if not is_correct_mc(picked_song_id, self.current.song["id"]):
                return False
            await self._award_and_end(user_id)
            return True

    async def vote_skip(self, user_id):
        """Majority skip among ACTIVE players (guessers + voters). One vote each.
        Returns 'skipped' | 'voted' | 'already' | None(no live round)."""
        async with self.lock:
            if self.round_ended:
                return None
            if user_id in self.skip_votes:
                return "already"
            self.skip_votes.add(user_id)
            active = self.answered_active | self.skip_votes
            if len(self.skip_votes) > 0.5 * len(active):
                self.skipped_song_ids.add(self.current.song["id"])
                await self._end_round(winner=None, points=0, reason="skip")
                return "skipped"
            return "voted"

    # ---- internals (always called while holding self.lock) ------------------
    async def _award_and_end(self, user_id):
        pts = self.points[self.stage]
        elapsed_ms = int((self.clock() - self.q_start) * 1000)
        self.scores[user_id] += pts
        prev = self.fastest.get(user_id)
        if prev is None or elapsed_ms < prev:
            self.fastest[user_id] = elapsed_ms
        if self.scoring_enabled:
            from bot import scoring
            scoring.record_correct(self.conn, self.guild_id, user_id, pts, elapsed_ms)
        await self._end_round(winner=user_id, points=pts, reason="correct")

    async def _end_round(self, winner, points, reason):
        if self.round_ended:
            return
        self.round_ended = True
        self._cancel_timeline()
        await self.presenter.reveal(self, self.current, winner, points, reason)
        if self.manage_timeline:
            self._advance_task = asyncio.create_task(self._goto_next())

    def _cancel_timeline(self):
        t = self._timeline_task
        # Don't cancel ourselves: the timeout path ends the round FROM the timeline.
        if t is not None and t is not asyncio.current_task() and not t.done():
            t.cancel()

    async def _goto_next(self):
        await asyncio.sleep(self.reveal_pause)
        if self.idx + 1 < len(self.questions):
            await self._start_question(self.idx + 1)
        else:
            async with self.lock:
                self.finished = True
            await self.presenter.game_over(self)

    # ---- teardown -----------------------------------------------------------
    async def end_game(self):
        """Hard stop (e.g. /end): close the round and cancel pending tasks."""
        async with self.lock:
            self.round_ended = True
            self.finished = True
        self._cancel_timeline()
        if self._advance_task and not self._advance_task.done():
            self._advance_task.cancel()
        await self.presenter.game_over(self)
