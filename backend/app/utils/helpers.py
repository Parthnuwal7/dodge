from pathlib import Path


def ensure_directory(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize_label(name: str) -> str:
    """Convert a folder/entity name to a PascalCase Neo4j node label.

    Example: 'sales_order_headers' -> 'SalesOrderHeaders'
    """
    return "".join(part.capitalize() for part in name.split("_"))
