-- name: find_path
-- description: Find shortest path between two node types, optionally filtered by properties
-- params: start_label, end_label
MATCH (a:`${start_label}` {`${start_property}`: '${start_value}'}),
      (b:`${end_label}` {`${end_property}`: '${end_value}'}),
      path = shortestPath((a)-[*..10]-(b))
RETURN path
LIMIT 5