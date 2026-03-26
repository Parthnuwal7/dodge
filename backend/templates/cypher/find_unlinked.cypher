-- name: find_unlinked
-- description: Find nodes that lack a specific relationship to another node type
-- params: label, relationship_type, target_label
MATCH (n:`${label}`)
WHERE NOT EXISTS { MATCH (n)-[:`${relationship_type}`]-(:`${target_label}`) }
RETURN n
LIMIT 500