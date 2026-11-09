"""Encrypted client records with an audit trail.

Everything about a client (names, plans, scenarios and audit details) is
encrypted with a key derived from the adviser's passphrase before it is
written to disk. Only ids and timestamps are stored in the clear. Without the
passphrase the database file can't be read.

Every saved plan is kept as a new version and never overwritten, so the
assumptions behind any past forecast can always be retrieved. Each save
writes an audit entry listing what changed and the effect on the forecast.
"""

from .store import AuditEntry, ClientStore, WrongPassphrase

__all__ = ["AuditEntry", "ClientStore", "WrongPassphrase"]
