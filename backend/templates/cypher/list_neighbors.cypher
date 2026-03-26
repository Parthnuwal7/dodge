-- name: list_neighbors
-- description: List all nodes directly connected to a given node (supports alternate identifiers)
-- params: label, where_clause
MATCH (n:`${label}`)
WHERE ${where_clause}
MATCH (n)-[r]-(m)
RETURN n, r, m
LIMIT 50