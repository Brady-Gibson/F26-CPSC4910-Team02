-- Read-only checks immediately after migration 002, before resuming writers.
USE Team02_DB;

-- Expected: no rows. Every legacy assignment must retain all its values.
SELECT d.driver_id, d.sponsor_id, d.current_points AS legacy_points,
       ds.current_points AS membership_points
FROM DRIVER d
LEFT JOIN DRIVER_SPONSOR ds
    ON ds.driver_id = d.driver_id AND ds.sponsor_id = d.sponsor_id
WHERE d.sponsor_id IS NOT NULL
  AND (ds.driver_id IS NULL OR d.current_points <> ds.current_points
       OR d.participation_status <> ds.participation_status
       OR d.joined_at <> ds.joined_at);

-- Compare by sponsor, never by a combined driver spending balance.
SELECT sponsor_id, COUNT(*) AS membership_count, SUM(current_points) AS points
FROM DRIVER_SPONSOR
GROUP BY sponsor_id
ORDER BY sponsor_id;

-- Expected: no rows. These should also be enforced by the new foreign keys.
SELECT i.cart_id, i.sponsor_id AS item_sponsor, c.sponsor_id AS cart_sponsor
FROM CART_ITEM i JOIN SHOPPING_CART c ON c.cart_id = i.cart_id
WHERE i.sponsor_id <> c.sponsor_id;

SELECT i.order_id, i.sponsor_id AS item_sponsor, o.sponsor_id AS order_sponsor
FROM ORDER_ITEM i JOIN CUSTOMER_ORDER o ON o.order_id = i.order_id
WHERE i.sponsor_id <> o.sponsor_id;

-- After successful migration: 19 base tables and 36 foreign keys.
SELECT COUNT(*) AS table_count
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE';

SELECT COUNT(*) AS foreign_key_count
FROM information_schema.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'FOREIGN KEY';
