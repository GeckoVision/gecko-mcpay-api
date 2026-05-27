"""Decision-data pipeline — extract / transform / persist.

Sub-modules are imported on-demand; do not eagerly import them here so that
extract.py works before transform.py / persist.py exist.
"""
