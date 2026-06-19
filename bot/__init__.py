"""Runtime bot package for the "guess MV by frame" Vpop game.

Catalog (songs/aliases/frames) is READ-ONLY here; the bot derives tier from
view_count and filters year at play time. The only table the bot writes is
`scores`. See the plan in CLAUDE.md for the full contract.
"""
