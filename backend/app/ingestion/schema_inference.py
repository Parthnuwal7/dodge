from itertools import combinations

import pandas as pd
from pydantic import BaseModel

from app.utils.logger import get_logger

logger = get_logger("ingestion.schema_inference")


class CandidateJoin(BaseModel):
    source_entity: str
    target_entity: str
    source_field: str
    target_field: str
    confidence: float


class SchemaInference:
    # Suffixes that strongly indicate an ID / foreign-key column
    _ID_SUFFIXES = ("id", "key", "code", "number", "document", "order", "partner", "material", "plant", "customer")

    def __init__(self, dataframes: dict[str, pd.DataFrame]) -> None:
        self.dataframes = dataframes

    def detect_id_columns(self, df: pd.DataFrame) -> list[str]:
        """Detect columns that are likely ID or foreign-key fields."""
        id_cols: list[str] = []
        for col in df.columns:
            col_lower = col.lower()

            # Heuristic 1: name ends with a known ID suffix
            if any(col_lower.endswith(suffix) for suffix in self._ID_SUFFIXES):
                id_cols.append(col)
                continue

            # Heuristic 2: string/object column with high cardinality relative to row count
            if df[col].dtype == object and len(df) > 0:
                try:
                    nunique = df[col].nunique()
                except TypeError:
                    # Column contains unhashable types (e.g. nested dicts)
                    continue
                ratio = nunique / len(df)
                if ratio > 0.8 and nunique > 10:
                    id_cols.append(col)

        return id_cols

    def detect_overlapping_values(self) -> list[CandidateJoin]:
        """Find columns across different entities that share overlapping values."""
        candidates: list[CandidateJoin] = []

        # Build a map of entity -> id columns -> unique value sets
        entity_id_sets: dict[str, dict[str, set]] = {}
        for entity_name, df in self.dataframes.items():
            id_cols = self.detect_id_columns(df)
            entity_id_sets[entity_name] = {}
            for col in id_cols:
                try:
                    values = set(df[col].dropna().astype(str).unique())
                except TypeError:
                    continue
                if values:
                    entity_id_sets[entity_name][col] = values

        # Compare every pair of entities
        entity_names = list(entity_id_sets.keys())
        for src_entity, tgt_entity in combinations(entity_names, 2):
            for src_col, src_values in entity_id_sets[src_entity].items():
                for tgt_col, tgt_values in entity_id_sets[tgt_entity].items():
                    overlap = src_values & tgt_values
                    if not overlap:
                        continue

                    # Confidence = Jaccard-like: overlap relative to the smaller set
                    smaller = min(len(src_values), len(tgt_values))
                    confidence = len(overlap) / smaller if smaller > 0 else 0.0

                    if confidence < 0.3:
                        continue

                    candidates.append(CandidateJoin(
                        source_entity=src_entity,
                        target_entity=tgt_entity,
                        source_field=src_col,
                        target_field=tgt_col,
                        confidence=round(confidence, 4),
                    ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def infer_candidate_joins(self) -> list[CandidateJoin]:
        """Main entry point: combine heuristics to produce ranked candidate joins."""
        candidates = self.detect_overlapping_values()
        logger.info("Inferred %d candidate joins across %d entities", len(candidates), len(self.dataframes))

        # Log top candidates
        for c in candidates[:10]:
            logger.info(
                "  %s.%s <-> %s.%s  (confidence=%.4f)",
                c.source_entity, c.source_field,
                c.target_entity, c.target_field,
                c.confidence,
            )

        return candidates
