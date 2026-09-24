-- Team 02 - Good Driver Incentive Program
-- Database Test Queries

USE Team02_DB;


-- =====================================================
-- TEST USERS
-- =====================================================

SELECT *
FROM USER_ACCOUNT
WHERE user_id >= 900000;


-- =====================================================
-- TEST SPONSOR
-- =====================================================

SELECT *
FROM SPONSOR_ORGANIZATION
WHERE sponsor_id = 900001;


-- =====================================================
-- TEST DRIVER
-- =====================================================

SELECT *
FROM DRIVER
WHERE driver_id = 900003;


-- Show driver information with sponsor name
SELECT
    u.username,
    u.first_name,
    u.last_name,
    s.sponsor_name,
    d.current_points,
    d.participation_status
FROM DRIVER d
JOIN USER_ACCOUNT u
    ON d.driver_id = u.user_id
LEFT JOIN SPONSOR_ORGANIZATION s
    ON d.sponsor_id = s.sponsor_id
WHERE d.driver_id = 900003;


-- =====================================================
-- DRIVER APPLICATION
-- =====================================================

SELECT
    application_id,
    driver_id,
    sponsor_id,
    status,
    decided_by_user_id,
    submitted_at,
    decision_at,
    reason
FROM DRIVER_APPLICATION
WHERE driver_id = 900003;


-- =====================================================
-- POINT HISTORY
-- =====================================================

SELECT
    point_transaction_id,
    driver_id,
    sponsor_id,
    performed_by_user_id,
    points_delta,
    balance_after,
    reason,
    created_at
FROM POINT_TRANSACTION
WHERE driver_id = 900003
ORDER BY point_transaction_id;


-- =====================================================
-- RECURRING POINT SCHEDULE
-- =====================================================

SELECT *
FROM RECURRING_POINT_SCHEDULE
WHERE driver_id = 900003;


-- =====================================================
-- PRODUCT AND SPONSOR CATALOG
-- =====================================================

SELECT *
FROM PRODUCT
WHERE product_id = 900001;

SELECT *
FROM CATALOG_ITEM
WHERE sponsor_id = 900001;


-- =====================================================
-- SHOPPING CART
-- =====================================================

SELECT *
FROM SHOPPING_CART
WHERE driver_id = 900003;

SELECT *
FROM CART_ITEM
WHERE cart_id = 900001;


-- =====================================================
-- CUSTOMER ORDER
-- =====================================================

SELECT *
FROM CUSTOMER_ORDER
WHERE driver_id = 900003;

SELECT *
FROM ORDER_ITEM
WHERE order_id = 900001;


-- =====================================================
-- CATALOG -> CART -> ORDER FLOW
-- =====================================================

SELECT
    p.product_name,
    ci.point_price,
    sc.status AS cart_status,
    cart.quantity AS cart_quantity,
    co.status AS order_status,
    co.total_points,
    oi.quantity AS ordered_quantity,
    oi.unit_point_price
FROM PRODUCT p
JOIN CATALOG_ITEM ci
    ON p.product_id = ci.product_id
JOIN CART_ITEM cart
    ON ci.sponsor_id = cart.sponsor_id
    AND ci.product_id = cart.product_id
JOIN SHOPPING_CART sc
    ON cart.cart_id = sc.cart_id
JOIN ORDER_ITEM oi
    ON ci.sponsor_id = oi.sponsor_id
    AND ci.product_id = oi.product_id
JOIN CUSTOMER_ORDER co
    ON oi.order_id = co.order_id
WHERE sc.driver_id = 900003;


-- =====================================================
-- NOTIFICATIONS AND ALERT SETTINGS
-- =====================================================

SELECT *
FROM ALERT_PREFERENCE
WHERE user_id = 900003;

SELECT *
FROM NOTIFICATION
WHERE user_id = 900003;


-- =====================================================
-- AUDIT HISTORY
-- =====================================================

SELECT *
FROM AUDIT_EVENT
WHERE driver_id = 900003;


-- =====================================================
-- ABOUT RELEASE
-- =====================================================

SELECT *
FROM ABOUT_RELEASE
WHERE team_number = 2;


-- =====================================================
-- DATABASE STRUCTURE CHECKS
-- =====================================================

-- Should return 18 tables
SELECT COUNT(*) AS total_tables
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'Team02_DB'
  AND TABLE_TYPE = 'BASE TABLE';


-- Should return 30 foreign-key relationships
SELECT COUNT(*) AS total_foreign_keys
FROM information_schema.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = 'Team02_DB'
  AND CONSTRAINT_TYPE = 'FOREIGN KEY';
