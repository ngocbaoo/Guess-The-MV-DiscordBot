"""Discord entry point: slash commands + the live presenter.

Run:  set DISCORD_TOKEN=...  &&  python -m bot.bot
(Generate db/bot.db first with `python crawl.py ingest`.)

One GameSession per channel. Frames are shown as a single message per question
that is EDITED at each stage (image + hint), per the approved plan.
"""
import os
import random

import discord
from discord import app_commands

from bot import scoring
from bot.config import DEFAULT_N, END_TYPING, END_MC, STEPS_TYPING
from bot.db import connect, resolve_frame_path
from bot.game import GameSession, Presenter, build_questions
from bot.masking import letters_ratio_at, mask_name
from bot.selection import build_pool, pick_questions

DIFFICULTY_CHOICES = [
    app_commands.Choice(name="all", value="all"),
    app_commands.Choice(name="easy", value="easy"),
    app_commands.Choice(name="medium", value="medium"),
    app_commands.Choice(name="hard", value="hard"),
]
MODE_CHOICES = [
    app_commands.Choice(name="typing", value="typing"),
    app_commands.Choice(name="mc", value="mc"),
]


def _stage_elapsed(session, stage):
    """Seconds into the question that `stage` corresponds to (for hint level)."""
    return session.steps[stage]


def _render_embed(session, q, stage):
    """Build the embed for a question stage (image is attached separately)."""
    elapsed = _stage_elapsed(session, stage)
    pts = session.points[stage]
    if session.mode == "typing":
        ratio = letters_ratio_at(elapsed)
        title_hint = mask_name(q.song["title"], ratio, q.seed)
        embed = discord.Embed(title="🎬 Đoán MV qua frame",
                              description=f"`{title_hint}`")
        if elapsed >= 30:  # artist revealed at the 30s checkpoint
            embed.add_field(name="Ca sĩ", value=q.song["artist"] or "?", inline=True)
    else:
        embed = discord.Embed(title="🎬 Đoán MV qua frame (trắc nghiệm)",
                              description="Chọn đáp án bên dưới!")
    embed.set_footer(text=f"Câu {session.idx + 1}/{len(session.questions)} • "
                          f"Điểm hiện tại: {pts}")
    embed.set_image(url="attachment://frame.jpg")
    return embed


def _frame_file(q, stage):
    path = resolve_frame_path(q.frames[stage]["file_path"])
    return discord.File(str(path), filename="frame.jpg")


class _MCView(discord.ui.View):
    def __init__(self, session, q):
        super().__init__(timeout=None)
        self.session = session
        for opt in q.mc_options:
            self.add_item(_MCButton(opt["id"], opt["title"]))


class _MCButton(discord.ui.Button):
    def __init__(self, song_id, title):
        super().__init__(label=title[:80] or "?", style=discord.ButtonStyle.primary)
        self.song_id = song_id

    async def callback(self, interaction: discord.Interaction):
        view: _MCView = self.view
        result = await view.session.submit_mc(interaction.user.id, self.song_id)
        if result is True:
            await interaction.response.send_message(
                f"✅ {interaction.user.mention} đúng!", ephemeral=False)
        elif result is False:
            await interaction.response.send_message("❌ Sai rồi!", ephemeral=True)
        else:
            await interaction.response.send_message("Câu đã kết thúc.", ephemeral=True)


class DiscordPresenter(Presenter):
    """One presenter per session, bound to a text channel."""

    def __init__(self, channel):
        self.channel = channel
        self.message = None

    async def show_question(self, session, q):
        embed = _render_embed(session, q, 0)
        view = _MCView(session, q) if session.mode == "mc" and q.mc_options else None
        if session.mode == "mc" and not q.mc_options:
            await self.channel.send(
                "⚠️ Không đủ bài để dựng trắc nghiệm cho câu này — bỏ qua.")
        self.message = await self.channel.send(
            embed=embed, file=_frame_file(q, 0), view=view)

    async def update_stage(self, session, q, stage):
        if self.message is None:
            return
        embed = _render_embed(session, q, stage)
        await self.message.edit(
            embed=embed, attachments=[_frame_file(q, stage)])

    async def reveal(self, session, q, winner, points, reason):
        title = q.song["title"]
        artist = q.song["artist"] or "?"
        if reason == "correct":
            who = f"<@{winner}>"
            head = f"✅ {who} đoán đúng (+{points} điểm)!"
        elif reason == "skip":
            head = "⏭️ Câu đã bị bỏ qua."
        else:
            head = "⏰ Hết giờ!"
        embed = discord.Embed(
            title=head, description=f"Đáp án: **{title}** — {artist}",
            url=q.song.get("url") or None)
        await self.channel.send(embed=embed)

    async def game_over(self, session):
        await self.channel.send(embed=_scoreboard_embed(session, final=True))


def _scoreboard_embed(session, final=False):
    rows = sorted(session.scores.items(), key=lambda kv: kv[1], reverse=True)
    lines = [f"**{i+1}.** <@{uid}> — {pts} điểm"
             for i, (uid, pts) in enumerate(rows)] or ["(chưa có điểm)"]
    title = "🏆 Kết quả ván" if final else "📊 Bảng điểm ván"
    return discord.Embed(title=title, description="\n".join(lines))


class TriviaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # needed to read typed guesses
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.conn = connect()
        self.sessions = {}  # channel_id -> GameSession

    async def setup_hook(self):
        await self.tree.sync()


client = TriviaBot()


@client.tree.command(name="play", description="Bắt đầu ván đoán MV qua frame")
@app_commands.describe(
    difficulty="Độ khó (tier theo view)", year_start="Năm bắt đầu",
    year_end="Năm kết thúc", n="Số câu", mode="Chế độ chơi")
@app_commands.choices(difficulty=DIFFICULTY_CHOICES, mode=MODE_CHOICES)
async def play(interaction: discord.Interaction,
               mode: app_commands.Choice[str],
               difficulty: app_commands.Choice[str] = None,
               year_start: int = None, year_end: int = None,
               n: int = DEFAULT_N):
    ch = interaction.channel_id
    if ch in client.sessions and not client.sessions[ch].finished:
        await interaction.response.send_message(
            "Kênh này đang có ván rồi. Dùng `/end` để kết thúc.", ephemeral=True)
        return

    diff = difficulty.value if difficulty else "all"
    pool = build_pool(client.conn, diff, year_start, year_end)
    if not pool:
        await interaction.response.send_message(
            "Không có bài nào khớp bộ lọc (cần ≥3 frame).", ephemeral=True)
        return

    rng = random.Random()
    chosen, truncated = pick_questions(pool, n, rng)
    questions = build_questions(client.conn, chosen, pool, mode.value, rng)

    note = (f"\n(Chỉ đủ {len(chosen)} bài cho bộ lọc này.)" if truncated else "")
    await interaction.response.send_message(
        f"▶️ Bắt đầu! {len(questions)} câu, chế độ **{mode.value}**.{note}")

    presenter = DiscordPresenter(interaction.channel)
    session = GameSession(client.conn, interaction.guild_id, ch, mode.value,
                          questions, presenter)
    client.sessions[ch] = session
    await session.start()


@client.tree.command(name="skip", description="Bỏ phiếu bỏ qua câu hiện tại")
async def skip(interaction: discord.Interaction):
    session = client.sessions.get(interaction.channel_id)
    if not session or session.finished:
        await interaction.response.send_message("Không có ván nào.", ephemeral=True)
        return
    result = await session.vote_skip(interaction.user.id)
    msg = {"skipped": "⏭️ Đủ phiếu — bỏ qua câu này!",
           "voted": "🗳️ Đã ghi phiếu bỏ qua.",
           "already": "Bạn đã bỏ phiếu rồi.",
           None: "Câu đã kết thúc."}[result]
    await interaction.response.send_message(msg, ephemeral=(result != "skipped"))


@client.tree.command(name="scoreboard", description="Bảng điểm ván hiện tại")
async def scoreboard(interaction: discord.Interaction):
    session = client.sessions.get(interaction.channel_id)
    if not session:
        await interaction.response.send_message("Không có ván nào.", ephemeral=True)
        return
    await interaction.response.send_message(embed=_scoreboard_embed(session))


@client.tree.command(name="end", description="Kết thúc ván và công bố thắng")
async def end(interaction: discord.Interaction):
    session = client.sessions.get(interaction.channel_id)
    if not session or session.finished:
        await interaction.response.send_message("Không có ván nào.", ephemeral=True)
        return
    await interaction.response.send_message("🛑 Kết thúc ván.")
    await session.end_game()


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    session = client.sessions.get(message.channel.id)
    if not session or session.finished or session.mode != "typing":
        return
    result = await session.submit_typing(message.author.id, message.content)
    if result is True:
        await message.add_reaction("✅")


def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Đặt biến môi trường DISCORD_TOKEN trước khi chạy.")
    client.run(token)


if __name__ == "__main__":
    main()
