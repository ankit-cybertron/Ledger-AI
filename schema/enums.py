"""
enums.py — Open, data-driven registries for Ledger AI v2 taxonomy.

Implements SourceType, Channel, Direction, and TransactionStatus registries
backed by an external configurable alias table (config/enum_aliases.json).

Rule: Unrecognized input always returns 'UNKNOWN' — never raises, never guesses.
Adding new raw synonyms to config/enum_aliases.json normalizes on the next run
without modifying Python code definitions.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "enum_aliases.json"


class ExtensibleRegistry:
    """
    Open, data-driven registry for taxonomy fields.
    Dynamically loads aliases from JSON configuration.
    """

    def __init__(self, category: str, default_value: str = "UNKNOWN"):
        self.category = category
        self.default_value = default_value
        self._aliases: Dict[str, str] = {}
        self._load_aliases()

    def _load_aliases(self) -> None:
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw_map = data.get(self.category, {})
                    self._aliases = {
                        str(k).strip().lower(): str(v).upper() for k, v in raw_map.items()
                    }
            except Exception:
                self._aliases = {}

    def normalize(self, raw_value: Optional[Any]) -> str:
        """
        Normalizes arbitrary free-text variants to a canonical string value.
        Unrecognized or null inputs return self.default_value ('UNKNOWN').
        Never raises exceptions, never guesses.
        """
        if raw_value is None:
            return self.default_value

        clean = str(raw_value).strip().lower()
        if not clean:
            return self.default_value

        # Always re-sync aliases to pick up live config updates without restart
        self._load_aliases()

        return self._aliases.get(clean, self.default_value)


# Global Instances exposing .normalize(raw_value)
SourceType = ExtensibleRegistry("SourceType", default_value="UNKNOWN")
Channel = ExtensibleRegistry("Channel", default_value="UNKNOWN")
Direction = ExtensibleRegistry("Direction", default_value="UNKNOWN")
TransactionStatus = ExtensibleRegistry("TransactionStatus", default_value="UNKNOWN")
