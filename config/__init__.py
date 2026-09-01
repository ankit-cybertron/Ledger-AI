"""
Config package for Ledger AI v2.
Contains matching engine configuration dataclass and default parameters.
"""

from config.matching_config import MatchingConfig

APP_VERSION = "v2.10"

__all__ = ["MatchingConfig", "APP_VERSION"]
