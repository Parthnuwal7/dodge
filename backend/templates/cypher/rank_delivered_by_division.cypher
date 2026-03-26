-- name: rank_delivered_by_division
-- description: Rank plants by delivered products for a given product division
-- params: division_value
MATCH (d:`Delivery`)-[:FULFILLS]->(so:`SalesOrder`)-[r:`CONTAINS`]->(p:`Product`)
MATCH (d)-[:SHIPS_FROM]->(pl:`Plant`)
WHERE p.`division` = '${division_value}'
RETURN pl, count(r) AS relationship_count
ORDER BY relationship_count DESC
LIMIT 10
