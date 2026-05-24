"""Structure-feature package for the Gecko trade lab.

Pure, strictly-causal market-structure primitives + Phase V Feature conformers.
Mirrors the contest_bot/indicators.py pattern: pure functions, no I/O, no
network, no live-bot state. Every function reads only candles[:i+1].
"""
