from pydantic import BaseModel

from app.utils.logger import get_logger

logger = get_logger("query.path_extractor")


class GraphNode(BaseModel):
    id: str
    label: str
    properties: dict


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    properties: dict


class GraphPath(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []


class PathExtractor:
    """Extracts structured node/edge data from raw Neo4j result records for graph highlighting."""

    def extract(self, raw_records: list[dict]) -> GraphPath:
        """Parse Neo4j result records and extract unique nodes and edges."""
        nodes_map: dict[str, GraphNode] = {}
        edges_list: list[GraphEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()

        for record in raw_records:
            for value in record.values():
                self._process_value(value, nodes_map, edges_list, seen_edges)

        return GraphPath(
            nodes=list(nodes_map.values()),
            edges=edges_list,
        )

    def _process_value(
        self,
        value,
        nodes_map: dict[str, GraphNode],
        edges_list: list[GraphEdge],
        seen_edges: set[tuple[str, str, str]],
    ) -> None:
        """Process a single value from a Neo4j record."""
        if value is None:
            return

        # Neo4j driver Node object
        if hasattr(value, "labels") and hasattr(value, "element_id"):
            self._extract_node(value, nodes_map)
            return

        # Neo4j driver Relationship object
        if hasattr(value, "type") and hasattr(value, "start_node") and hasattr(value, "end_node"):
            self._extract_edge(value, nodes_map, edges_list, seen_edges)
            return

        # Neo4j driver Path object
        if hasattr(value, "nodes") and hasattr(value, "relationships"):
            for n in value.nodes:
                self._extract_node(n, nodes_map)
            for r in value.relationships:
                self._extract_edge(r, nodes_map, edges_list, seen_edges)
            return

        # Neo4j Node (dict with _id, _labels, _properties or element_id)
        if isinstance(value, dict):
            if "_labels" in value or "labels" in value:
                self._extract_node(value, nodes_map)
            elif "_type" in value or "type" in value:
                self._extract_edge(value, nodes_map, edges_list, seen_edges)
            # Path objects from Neo4j driver come as dicts with nodes/relationships
            elif "nodes" in value and "relationships" in value:
                for n in value["nodes"]:
                    self._extract_node(n, nodes_map)
                for r in value["relationships"]:
                    self._extract_edge(r, nodes_map, edges_list, seen_edges)

        # List of values (e.g., from COLLECT or path results)
        elif isinstance(value, list):
            for item in value:
                self._process_value(item, nodes_map, edges_list, seen_edges)

    def _extract_node(self, data, nodes_map: dict[str, GraphNode]) -> None:
        """Extract a GraphNode from a Neo4j node dict."""
        if isinstance(data, dict):
            node_id = str(
                data.get("element_id")
                or data.get("_id")
                or data.get("id")
                or id(data)
            )
        else:
            node_id = str(getattr(data, "element_id", None) or id(data))

        if node_id in nodes_map:
            return

        if isinstance(data, dict):
            labels = data.get("_labels") or data.get("labels") or []
            props = data.get("_properties") or data.get("properties") or {}
        else:
            labels = list(getattr(data, "labels", []) or [])
            props = dict(getattr(data, "_properties", {}) or {})

        label = labels[0] if labels else "Unknown"

        # If neither _properties nor properties exists, treat remaining keys as properties
        if not props and isinstance(data, dict):
            skip_keys = {"_id", "_labels", "labels", "element_id", "id", "_properties", "properties"}
            props = {k: v for k, v in data.items() if k not in skip_keys}

        nodes_map[node_id] = GraphNode(id=node_id, label=label, properties=props)

    def _extract_edge(
        self,
        data,
        nodes_map: dict[str, GraphNode],
        edges_list: list[GraphEdge],
        seen_edges: set[tuple[str, str, str]],
    ) -> None:
        """Extract a GraphEdge from a Neo4j relationship dict."""
        if isinstance(data, dict):
            rel_type = data.get("_type") or data.get("type") or "UNKNOWN"
            start_id = str(
                data.get("_start_node_element_id")
                or data.get("start_node_element_id")
                or data.get("source")
                or ""
            )
            end_id = str(
                data.get("_end_node_element_id")
                or data.get("end_node_element_id")
                or data.get("target")
                or ""
            )
            props = data.get("_properties") or data.get("properties") or {}
        else:
            rel_type = str(getattr(data, "type", "UNKNOWN"))
            start_node = getattr(data, "start_node", None)
            end_node = getattr(data, "end_node", None)
            start_id = str(getattr(start_node, "element_id", "") or "")
            end_id = str(getattr(end_node, "element_id", "") or "")
            props = dict(getattr(data, "_properties", {}) or {})
            if start_node is not None:
                self._extract_node(start_node, nodes_map)
            if end_node is not None:
                self._extract_node(end_node, nodes_map)


        key = (start_id, end_id, rel_type)
        if key in seen_edges:
            return
        seen_edges.add(key)

        edges_list.append(GraphEdge(
            source=start_id,
            target=end_id,
            type=rel_type,
            properties=props,
        ))
