"""Compliance-checking library.

Layout:
    rules.py     every threshold and pattern, so a rule change is a one-file edit
    model.py     CheckResult and Span, the two things passed around
    extract.py   turns a PDF into positioned text and geometry
    checks/      one module per rule; checks/__init__.py runs them in order
"""
