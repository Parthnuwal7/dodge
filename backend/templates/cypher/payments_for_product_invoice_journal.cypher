-- name: payments_for_product_invoice_journal
-- description: Payments linked via JournalEntry to Invoices for a given Product identifier
-- params: product_identifier
MATCH (p:`Product`)
WHERE p.`product` = '${product_identifier}' OR p.`productOldId` = '${product_identifier}'
MATCH (i:`Invoice`)-[:INVOICES]->(p)
MATCH (i)-[:GENERATES]->(je:`JournalEntry`)
MATCH (je)-[:CLEARED_BY]->(pay:`Payment`)
RETURN pay, je, i, p
LIMIT 500
