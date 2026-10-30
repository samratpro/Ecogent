"""
Ecogent - a token-efficient browser agent.

The LLM plans, picks elements on cache misses, heals and analyzes.
Python (Playwright + BeautifulSoup) executes everything deterministically and
remembers what worked in plan.json so later runs need few or zero LLM tokens.
"""

__version__ = "0.2.0"
