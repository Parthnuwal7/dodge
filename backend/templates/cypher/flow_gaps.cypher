-- name: flow_gaps
-- description: Find sales orders with incomplete Order-to-Cash flows (missing delivery, billing, journal entry, or payment)
-- params:
MATCH (so:`SalesOrder`)
OPTIONAL MATCH (so)<-[:FULFILLS]-(d:`Delivery`)
OPTIONAL MATCH (inv:`Invoice`)-[:BILLS]->(d)
OPTIONAL MATCH (inv)-[:GENERATES]->(je:`JournalEntry`)
OPTIONAL MATCH (je)-[:CLEARED_BY]->(pay:`Payment`)
WITH so,
     count(DISTINCT d) > 0 AS has_delivery,
     count(DISTINCT inv) > 0 AS has_invoice,
     count(DISTINCT je) > 0 AS has_journal_entry,
     count(DISTINCT pay) > 0 AS has_payment
WHERE NOT (has_delivery AND has_invoice AND has_journal_entry AND has_payment)
RETURN so.`salesOrder` AS sales_order,
       has_delivery,
       has_invoice,
       has_journal_entry,
       has_payment,
       CASE
         WHEN NOT has_delivery THEN 'No delivery'
         WHEN has_delivery AND NOT has_invoice THEN 'Delivered but not billed'
         WHEN has_invoice AND NOT has_journal_entry THEN 'Billed but no journal entry'
         WHEN has_journal_entry AND NOT has_payment THEN 'No payment'
         ELSE 'Incomplete flow'
       END AS gap_type
ORDER BY gap_type
LIMIT 50