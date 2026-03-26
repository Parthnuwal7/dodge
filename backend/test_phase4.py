"""Phase 4 test script. Run from backend/ with venv activated:
    python test_phase4.py
"""
from app.config.settings import get_settings
from app.graph.neo4j_client import Neo4jClient
from app.services.graph_service import GraphService


def main():
    s = get_settings()

    # 1. Test connectivity
    print("=== Step 1: Testing Neo4j connectivity ===")
    client = Neo4jClient(s.neo4j_uri, s.neo4j_user, s.neo4j_password)
    client.verify_connectivity()
    result = client.execute("RETURN 1 AS test")
    print(f"Connection OK: {result}")

    # 2. Run full ingestion
    print("\n=== Step 2: Running full ingestion pipeline ===")
    service = GraphService.create(s.data_dir, client)
    report = service.ingest(clear_existing=True)

    print("\n=== BUILD REPORT ===")
    print("Nodes:")
    for label, count in report.nodes_created.items():
        print(f"  {label}: {count}")
    print("Edges:")
    for etype, count in report.edges_created.items():
        print(f"  {etype}: {count}")
    if report.errors:
        print("Errors:")
        for e in report.errors:
            print(f"  {e}")

    # 3. Verify data
    print("\n=== Step 3: Verifying data in Neo4j ===")
    result = client.execute(
        "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC"
    )
    print("Node counts:")
    for r in result:
        print(f"  {r['label']}: {r['count']}")

    result = client.execute(
        "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY count DESC LIMIT 10"
    )
    print("\nTop relationship counts:")
    for r in result:
        print(f"  {r['type']}: {r['count']}")

    # 4. Export schema for inspection
    service.export_schema("graph_schema.json")
    print("\nSchema exported to graph_schema.json")

    client.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
