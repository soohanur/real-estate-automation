"""
Permanent KVK Storage Module

Stores all collected property KVK numbers permanently across sessions.
This ensures we never re-collect the same property.
"""
import json
import logging
from pathlib import Path
from typing import Set, List
from threading import Lock

logger = logging.getLogger('funda.kvk_storage')


class KvkStorage:
    """
    Persistent storage for property KVK numbers.
    Thread-safe with file locking.
    """

    def __init__(self, storage_file: str | Path = None):
        """
        Initialize KVK storage.

        Args:
            storage_file: Path to JSON file for persistent storage.
                          Default: funda/data/permanent_kvk.json
        """
        if storage_file is None:
            storage_file = Path(__file__).parent.parent.parent / 'data' / 'permanent_kvk.json'
        
        self.storage_file = Path(storage_file)
        self._lock = Lock()
        self._kvk_set: Set[str] = set()
        self._load()

    def _load(self) -> None:
        """Load KVK numbers from disk."""
        with self._lock:
            if self.storage_file.exists():
                try:
                    with open(self.storage_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self._kvk_set = set(data.get('kvk_numbers', []))
                    logger.info(f"Loaded {len(self._kvk_set)} KVK numbers from permanent storage")
                except Exception as e:
                    logger.warning(f"Could not load KVK storage: {e}")
                    self._kvk_set = set()
            else:
                self._kvk_set = set()
                logger.info("No permanent KVK storage found - starting fresh")

    def _save(self) -> None:
        """Save KVK numbers to disk."""
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'kvk_numbers': sorted(list(self._kvk_set)),
                    'total_count': len(self._kvk_set)
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save KVK storage: {e}")

    def exists(self, kvk: str) -> bool:
        """Check if a KVK number already exists in storage."""
        with self._lock:
            return kvk in self._kvk_set

    def add(self, kvk: str) -> bool:
        """
        Add a KVK number to storage.

        Returns:
            True if added (was new), False if already existed.
        """
        with self._lock:
            if kvk in self._kvk_set:
                return False
            self._kvk_set.add(kvk)
            self._save()
            return True

    def remove(self, kvk: str) -> bool:
        """Remove a KVK number from storage so the property can be deleted
        for good and never re-collected. Returns True if it was present."""
        with self._lock:
            if kvk not in self._kvk_set:
                return False
            self._kvk_set.discard(kvk)
            self._save()
            return True

    def add_many(self, kvk_numbers: List[str]) -> int:
        """
        Add multiple KVK numbers.

        Returns:
            Number of new KVKs added (excluding duplicates).
        """
        added_count = 0
        with self._lock:
            for kvk in kvk_numbers:
                if kvk not in self._kvk_set:
                    self._kvk_set.add(kvk)
                    added_count += 1
            if added_count > 0:
                self._save()
        return added_count

    def filter_new(self, kvk_numbers: List[str]) -> List[str]:
        """
        Filter out already-known KVK numbers.

        Returns:
            List of KVK numbers that are not yet in storage.
        """
        with self._lock:
            return [k for k in kvk_numbers if k not in self._kvk_set]

    def get_all(self) -> Set[str]:
        """Get all stored KVK numbers."""
        with self._lock:
            return self._kvk_set.copy()

    def count(self) -> int:
        """Get total count of stored KVK numbers."""
        with self._lock:
            return len(self._kvk_set)

    def clear(self) -> None:
        """Clear all stored KVK numbers (for fresh start)."""
        with self._lock:
            self._kvk_set.clear()
            self._save()
            logger.info("Permanent KVK storage cleared")

    def remove(self, kvk: str) -> bool:
        """Remove a single KVK from storage."""
        with self._lock:
            if kvk in self._kvk_set:
                self._kvk_set.discard(kvk)
                self._save()
                return True
            return False


# Global instance for easy access
_storage_instance: KvkStorage | None = None


def get_kvk_storage(storage_file: str | Path = None) -> KvkStorage:
    """Get or create the global KVK storage instance."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = KvkStorage(storage_file)
    return _storage_instance


def reset_storage():
    """Reset the global storage instance (for testing)."""
    global _storage_instance
    _storage_instance = None
