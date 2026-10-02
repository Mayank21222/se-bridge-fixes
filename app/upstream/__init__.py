"""Upstream integration: the polite HTTP client, the parsers and the URL table.

Nothing outside this package performs network I/O against the target site, and
nothing outside :mod:`app.upstream.parsers` knows what its markup looks like.
"""
