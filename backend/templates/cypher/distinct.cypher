-- name: distinct
-- description: List distinct values of a specific property on nodes of a given label
-- params: label, property_name
MATCH (n:`${label}`)
WHERE n.`${property_name}` IS NOT NULL
RETURN DISTINCT n.`${property_name}` AS value, count(*) AS occurrences
ORDER BY occurrences DESC
LIMIT 100