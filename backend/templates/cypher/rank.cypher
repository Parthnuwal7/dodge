-- name: rank
-- description: Rank nodes by number of relationships to another node type (e.g. products with most invoices)
-- params: label, relationship_type, target_label
MATCH (n:`${label}`)-[r:`${relationship_type}`]-(m:`${target_label}`)
RETURN n, count(r) AS relationship_count
ORDER BY relationship_count DESC
LIMIT 500