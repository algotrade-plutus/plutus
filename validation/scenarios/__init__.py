"""Stress scenarios: real algorithms, real windows, read back from the logs.

Each module here is one question put to the assembled simulator. A scenario
owns its own window and its own clock, because the questions do not share one:
proving that an ATO evaporates at the opening cross needs two clock steps
inside 09:00-09:15, and proving that a day order dies at the close needs two
sessions. ``validation.runner.Scenario`` carries ``open_time`` and
``close_time`` for exactly this reason.

Nothing here decides a market outcome. Every number a scenario asserts on came
out of ``plutus.market.session``; if it is wrong, it is wrong in the simulator.
"""
