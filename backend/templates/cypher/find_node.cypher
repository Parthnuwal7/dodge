-- name: find_node
-- description: Find nodes by label and optional property filter (supports alternate identifiers)
-- params: label, where_clause
MATCH (n:`${label}`)
WHERE ${where_clause}
RETURN n
LIMIT 500