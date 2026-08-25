"""
matching_config.py — Configuration model for Ledger AI v2 matching engine.

Encapsulates all tunable thresholds, tolerances, and parameters currently used
across matcher/, reconciler/, and llm/ modules.

Supports serialization (to_dict/save) and deserialization (from_dict/load_from_json),
as well as environment variable overrides.
"""

import os
import json
from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import Optional, Dict, Any, Union


@dataclass
class MatchingConfig:
    """
    Tunable configuration parameters for reconciliation and matching.
    Default values preserve existing v1 behavior while enabling v2 extensions.
    """

    # Schema & Reproducibility (T7.3)
    schema_version: str = "2.0.0"

    # Tolerance & Window Rules
    date_tolerance_days: int = 3
    absolute_amount_tolerance: float = 1.00
    percentage_tolerance: Optional[float] = None
    max_tolerance_cap: Optional[float] = None

    # Similarity & Confidence Thresholds
    narration_similarity_threshold: float = 0.50
    ml_match_threshold: float = 0.95
    ml_review_threshold: float = 0.50
    llm_match_threshold: float = 0.70
    minimum_score_margin: float = 0.05

    # Strategy & Engine Toggles
    allow_split_settlements: bool = True
    allow_aggregated_settlements: bool = True
    fee_aware_matching: bool = True
    business_day_aware: bool = False

    # Trust & Mapping Floors
    source_confidence_auto_accept: float = 0.85
    source_confidence_needs_confirmation: float = 0.60
    column_mapping_confidence_floor: float = 0.60

    def to_dict(self) -> Dict[str, Any]:
        """
        Exports the configuration parameters to a dictionary.
        """
        return asdict(self)

    def save(self, path: Union[str, Path]) -> None:
        """
        Persists the configuration to a JSON file at path.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MatchingConfig":
        """
        Instantiates a MatchingConfig from a dictionary, mapping existing fields
        and using default values for missing ones.
        """
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields and v is not None}
        return cls(**filtered)

    @classmethod
    def load_from_json(cls, path: Union[str, Path]) -> "MatchingConfig":
        """
        Loads configuration parameters from a JSON file, falling back to defaults
        if the file does not exist or contains invalid JSON.
        """
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                return cls.from_dict(data)
        except Exception:
            return cls()

    @classmethod
    def load_with_env_overrides(cls, json_path: Optional[Union[str, Path]] = None) -> "MatchingConfig":
        """
        Loads configuration from a JSON file (if provided) and applies any matching
        environment variables (e.g. LEDGER_DATE_TOLERANCE_DAYS).
        """
        cfg = cls.load_from_json(json_path) if json_path else cls()
        
        # Apply environment overrides if set (prefixed with LEDGER_)
        for f in fields(cls):
            env_key = f"LEDGER_{f.name.upper()}"
            if env_key in os.environ:
                val = os.environ[env_key]
                try:
                    if f.type == int or f.type == Optional[int]:
                        setattr(cfg, f.name, int(val))
                    elif f.type == float or f.type == Optional[float]:
                        setattr(cfg, f.name, float(val))
                    elif f.type == bool:
                        setattr(cfg, f.name, val.lower() in ("true", "1", "yes"))
                    else:
                        setattr(cfg, f.name, val)
                except ValueError:
                    pass

        return cfg
