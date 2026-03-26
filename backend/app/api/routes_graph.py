from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config.constants import API_PREFIX
from app.config.settings import get_settings
from app.graph.graph_builder import BuildReport, GraphBuilder
from app.graph.neo4j_client import Neo4jClient
from app.ingestion.jsonl_loader import JsonlLoader
from app.ingestion.schema_inference import SchemaInference
from app.modeling.graph_schema import GraphSchema
from app.modeling.relationship_mapper import RelationshipMapper
from app.services.graph_service import GraphService
from app.utils.logger import get_logger

logger = get_logger("api.routes_graph")
router = APIRouter(prefix=f"{API_PREFIX}/graph", tags=["graph"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class PreviewRequest(BaseModel):
    data_dir: str | None = None


class PreviewResponse(BaseModel):
    graph_schema: dict[str, Any]
    node_count: int
    edge_count: int


class BuildRequest(BaseModel):
    graph_schema: dict[str, Any]
    clear_existing: bool = False


class BuildResponse(BaseModel):
    report: dict[str, Any]


class ExploreResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class StatusResponse(BaseModel):
    connected: bool
    node_labels: list[str]
    relationship_types: list[str]
    total_nodes: int
    total_relationships: int


class ClearResponse(BaseModel):
    message: str


class NeighborResponse(BaseModel):
    center_node: dict[str, Any]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_neo4j_client() -> Neo4jClient:
    settings = get_settings()
    return Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/preview", response_model=PreviewResponse)
def preview_schema(request: PreviewRequest):
    """Step 1: Load data + infer schema, return proposed GraphSchema for review.
    No data is written to Neo4j.
    """
    settings = get_settings()
    data_dir = request.data_dir or settings.data_dir

    try:
        # Load
        loader = JsonlLoader(data_dir)
        dataframes = loader.load_all()

        # Infer
        inference = SchemaInference(dataframes)
        candidate_joins = inference.infer_candidate_joins()

        # Map
        mapper = RelationshipMapper()
        schema = mapper.build_schema(dataframes, candidate_joins)

        return PreviewResponse(
            graph_schema=schema.model_dump(),
            node_count=len(schema.nodes),
            edge_count=len(schema.edges),
        )
    except Exception as e:
        logger.error("Preview failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/build", response_model=BuildResponse)
def build_graph(request: BuildRequest):
    """Step 2: Accept a (possibly user-edited) GraphSchema and build the graph in Neo4j."""
    client = _get_neo4j_client()
    try:
        # Validate and parse the schema
        schema = GraphSchema.model_validate(request.graph_schema)

        # Create builder and service
        builder = GraphBuilder(client, schema)

        # Load the data again for building
        settings = get_settings()
        loader = JsonlLoader(settings.data_dir)
        dataframes = loader.load_all()

        if request.clear_existing:
            builder.clear_graph()

        report = builder.build_all(dataframes)

        return BuildResponse(report=report.model_dump())
    except Exception as e:
        logger.error("Build failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()


@router.delete("/clear", response_model=ClearResponse)
def clear_graph():
    """Delete all nodes and relationships from the graph."""
    client = _get_neo4j_client()
    try:
        client.execute_write("MATCH (n) DETACH DELETE n")
        logger.info("Graph cleared via API")
        return ClearResponse(message="Graph cleared successfully")
    except Exception as e:
        logger.error("Clear failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()


@router.get("/explore", response_model=ExploreResponse)
def explore_graph(limit: int = 200):
    """Fetch a sample of nodes and relationships for visualization."""
    client = _get_neo4j_client()
    try:
        # Fetch nodes with labels and properties
        node_records = client.execute(
            "MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props "
            "LIMIT $limit",
            {"limit": limit},
        )
        nodes = [
            {
                "id": r["id"],
                "label": r["labels"][0] if r["labels"] else "Unknown",
                "properties": r["props"],
            }
            for r in node_records
        ]
        node_ids = {n["id"] for n in nodes}

        # Fetch relationships between the returned nodes
        edge_records = client.execute(
            "MATCH (a)-[r]->(b) "
            "WHERE elementId(a) IN $ids AND elementId(b) IN $ids "
            "RETURN elementId(a) AS source, elementId(b) AS target, type(r) AS type, properties(r) AS props "
            "LIMIT $limit",
            {"ids": list(node_ids), "limit": limit * 2},
        )
        edges = [
            {
                "source": r["source"],
                "target": r["target"],
                "type": r["type"],
                "properties": r["props"],
            }
            for r in edge_records
        ]

        return ExploreResponse(nodes=nodes, edges=edges)
    except Exception as e:
        logger.error("Explore failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()


@router.get("/status", response_model=StatusResponse)
def graph_status():
    """Return current graph database status and statistics."""
    client = _get_neo4j_client()
    try:
        connected = client.verify_connectivity()
        if not connected:
            return StatusResponse(
                connected=False,
                node_labels=[],
                relationship_types=[],
                total_nodes=0,
                total_relationships=0,
            )

        # Fetch labels
        labels_result = client.execute("CALL db.labels()")
        labels = [r.get("label", "") for r in labels_result]

        # Fetch relationship types
        rels_result = client.execute("CALL db.relationshipTypes()")
        rel_types = [r.get("relationshipType", "") for r in rels_result]

        # Counts
        node_count_result = client.execute("MATCH (n) RETURN count(n) AS total")
        total_nodes = node_count_result[0].get("total", 0) if node_count_result else 0

        rel_count_result = client.execute("MATCH ()-[r]->() RETURN count(r) AS total")
        total_rels = rel_count_result[0].get("total", 0) if rel_count_result else 0

        return StatusResponse(
            connected=True,
            node_labels=labels,
            relationship_types=rel_types,
            total_nodes=total_nodes,
            total_relationships=total_rels,
        )
    except Exception as e:
        logger.error("Status check failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()


@router.get("/neighbors/{node_id:path}", response_model=NeighborResponse)
def get_neighbors(node_id: str, limit: int = 50):
    """Fetch all neighbors of a given node by its elementId."""
    client = _get_neo4j_client()
    try:
        # Fetch the center node
        center_records = client.execute(
            "MATCH (n) WHERE elementId(n) = $nid "
            "RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props",
            {"nid": node_id},
        )
        if not center_records:
            raise HTTPException(status_code=404, detail="Node not found")

        center = {
            "id": center_records[0]["id"],
            "label": center_records[0]["labels"][0] if center_records[0]["labels"] else "Unknown",
            "properties": center_records[0]["props"],
        }

        # Fetch neighbors (both directions)
        neighbor_records = client.execute(
            "MATCH (n)-[r]-(m) WHERE elementId(n) = $nid "
            "RETURN elementId(m) AS id, labels(m) AS labels, properties(m) AS props, "
            "elementId(startNode(r)) AS source, elementId(endNode(r)) AS target, "
            "type(r) AS type, properties(r) AS rprops "
            "LIMIT $limit",
            {"nid": node_id, "limit": limit},
        )

        nodes_map: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        for r in neighbor_records:
            nid = r["id"]
            if nid not in nodes_map:
                nodes_map[nid] = {
                    "id": nid,
                    "label": r["labels"][0] if r["labels"] else "Unknown",
                    "properties": r["props"],
                }
            edges.append({
                "source": r["source"],
                "target": r["target"],
                "type": r["type"],
                "properties": r["rprops"],
            })

        return NeighborResponse(
            center_node=center,
            nodes=list(nodes_map.values()),
            edges=edges,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Neighbors fetch failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()
