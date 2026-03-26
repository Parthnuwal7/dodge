import json
from pathlib import Path

import pandas as pd

from app.config.constants import JSONL_EXTENSION
from app.utils.logger import get_logger

logger = get_logger("ingestion.jsonl_loader")


class JsonlLoader:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self._dataframes: dict[str, pd.DataFrame] = {}

    def load_file(self, file_path: str) -> pd.DataFrame:
        records: list[dict] = []
        path = Path(file_path)
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid JSON at %s:%d", path.name, line_num)
        return pd.DataFrame(records)

    def load_all(self) -> dict[str, pd.DataFrame]:
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")

        self._dataframes = {}

        for entity_dir in sorted(self.data_dir.iterdir()):
            if not entity_dir.is_dir():
                continue

            entity_name = entity_dir.name
            part_files = sorted(entity_dir.glob(f"*{JSONL_EXTENSION}"))

            if not part_files:
                logger.warning("No JSONL files found in %s", entity_dir)
                continue

            frames: list[pd.DataFrame] = []
            for pf in part_files:
                df = self.load_file(str(pf))
                if not df.empty:
                    frames.append(df)

            if frames:
                combined = pd.concat(frames, ignore_index=True)
                self._dataframes[entity_name] = combined
                logger.info(
                    "Loaded entity '%s': %d records, %d columns",
                    entity_name, len(combined), len(combined.columns),
                )
            else:
                logger.warning("No valid records for entity '%s'", entity_name)

        logger.info("Loaded %d entity types total", len(self._dataframes))
        return self._dataframes

    def get_schema_summary(self) -> dict[str, dict]:
        summary: dict[str, dict] = {}
        for entity_name, df in self._dataframes.items():
            summary[entity_name] = {
                "columns": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "row_count": len(df),
                "sample_values": {
                    col: df[col].dropna().head(3).tolist()
                    for col in df.columns
                },
            }
        return summary
