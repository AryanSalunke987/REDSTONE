"""
Database package for Smart PPE Compliance Monitoring System.
Provides SQLite-based storage for worker records and PPE scan events.
"""

from .db_manager import PPEDatabase, _normalize_uid

__all__ = ["PPEDatabase", "_normalize_uid"]
