-- name: customers_ordered_delivered_unpaid
-- description: Customers who ordered a product, received delivery, and have no payment
-- params: product_identifier
MATCH (c:`Customer`)-[:PLACED_ORDER]->(so:`SalesOrder`)-[:CONTAINS]->(p:`Product`)
MATCH (d:`Delivery`)-[:FULFILLS]->(so)
WHERE (p.`product` = '${product_identifier}' OR p.`productOldId` = '${product_identifier}')
AND NOT EXISTS { MATCH (:`Payment`)-[:PAID_BY]->(c) }
RETURN c, so, d, p
LIMIT 500
