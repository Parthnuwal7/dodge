-- name: find_latest
-- description: Find the most recent nodes of a given label, ordered by a date/time property
-- params: label, order_property, order_direction
MATCH (n:`${label}`)
WHERE n.`${order_property}` IS NOT NULL
RETURN n
ORDER BY n.`${order_property}` ${order_direction}
LIMIT 10