-- name: search
-- description: Search for a node by value across all its properties (useful when the exact property is unknown)
-- params: label, search_value
MATCH (n:`${label}`)
WHERE ANY(key IN keys(n) WHERE toString(n[key]) = '${search_value}')
RETURN n
LIMIT 500