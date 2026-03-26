-- name: count
-- description: Count nodes of a given label, optionally filtered by a property
-- params: label
MATCH (n:`${label}`)
RETURN count(n) AS total