"""
Ingestion package for Ledger AI v2.
Contains stage 1 file reading, table extraction, source detection, column mapping, normalization, quality reporting, status eligibility, and deduplication modules.
"""

from ingestion.file_reader import read_source_file, RawTable
from ingestion.source_detector import detect_source, SourceDetectionResult
from ingestion.column_mapper import map_columns, ColumnMapping
from ingestion.normalizer import normalize_row, parse_numeric
from ingestion.quality_report import build_quality_report, QualityReport
from ingestion.eligibility import filter_eligible
from ingestion.dedupe import detect_duplicates, DedupeReport

__all__ = [
    "read_source_file",
    "RawTable",
    "detect_source",
    "SourceDetectionResult",
    "map_columns",
    "ColumnMapping",
    "normalize_row",
    "parse_numeric",
    "build_quality_report",
    "QualityReport",
    "filter_eligible",
    "detect_duplicates",
    "DedupeReport",
]
