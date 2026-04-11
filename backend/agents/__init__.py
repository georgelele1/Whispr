"""
Whispr agent modules.

Each module owns one responsibility:
  refiner.py   — clean and format voice transcription text
  knowledge.py — look up facts, formulas, definitions
  router.py    — decide which agent/tool to call
  profile.py   — learn and cache user context
"""