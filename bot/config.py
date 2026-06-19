"""Tunable constants for the game. Kept in one place so timing/points are easy
to adjust without touching logic.
"""

# --- Typing mode: progressive reveal over 50s, 5 checkpoints (5->4->3->2->1) ---
STEPS_TYPING = [0, 10, 20, 30, 40]   # seconds at which a checkpoint fires
END_TYPING = 50                      # question ends here -> reveal answer
POINTS_TYPING = [5, 4, 3, 2, 1]      # points awarded if correct AT each checkpoint

# --- MC mode: time-decay over 30s, image changes thrice (5->3->1) ---
STEPS_MC = [0, 10, 20]
END_MC = 30
POINTS_MC = [5, 3, 1]

# Seconds-checkpoint -> fraction of letter positions revealed (typing mode only).
# 40s set must be a superset of 10s set (monotone); enforced in masking.py.
REVEAL_RATIOS = {10: 0.25, 40: 0.50}

# Typing match tolerance: accept exact alias hit OR rapidfuzz ratio >= this (%).
# Percentage-based so it is forgiving on long titles, strict on short ones.
FUZZY_RATIO_MIN = 80

DEFAULT_N = 10        # default number of questions per game
MIN_FRAMES = 3        # a song needs >=3 frames to be playable (3 distinct stages)

# Number of distinct options shown in MC mode (1 answer + 3 distractors).
MC_CHOICES = 4
