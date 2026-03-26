-- name: aggregate
-- description: Aggregate a numeric property on nodes of a given label
-- params: label, aggregate_function, property_name
MATCH (n:`${label}`)
WHERE n.`${property_name}` IS NOT NULL
RETURN ${aggregate_function}(toFloat(n.`${property_name}`)) AS result, count(n) AS total_nodes