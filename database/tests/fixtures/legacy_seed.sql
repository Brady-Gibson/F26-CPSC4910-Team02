-- Team 02 - Good Driver Incentive Program
-- Test / Seed Data

USE Team02_DB;


-- =====================================================
-- TEST USERS
-- =====================================================

INSERT INTO USER_ACCOUNT
(user_id, username, password_hash, first_name, last_name, email,
 phone, account_status)
VALUES
(900001, 'testadmin', 'TEST_HASH_ONLY', 'Test', 'Admin',
 'testadmin@example.com', '555-0001', 'ACTIVE'),

(900002, 'testsponsor', 'TEST_HASH_ONLY', 'Test', 'Sponsor',
 'testsponsor@example.com', '555-0002', 'ACTIVE'),

(900003, 'testdriver', 'TEST_HASH_ONLY', 'Test', 'Driver',
 'testdriver@example.com', '555-0003', 'ACTIVE');


-- Admin
INSERT INTO ADMIN (admin_id)
VALUES (900001);


-- Sponsor organization
INSERT INTO SPONSOR_ORGANIZATION
(sponsor_id, sponsor_name, status, point_dollar_rate,
 contact_email, phone)
VALUES
(900001, 'Tiger Test Trucking', 'ACTIVE', 0.01,
 'sponsor@example.com', '555-1000');


-- Sponsor user
INSERT INTO SPONSOR_USER
(sponsor_user_id, sponsor_id, job_title)
VALUES
(900002, 900001, 'Safety Manager');


-- Driver
INSERT INTO DRIVER
(driver_id, sponsor_id, current_points, participation_status)
VALUES
(900003, NULL, 0, 'APPLICANT');


-- =====================================================
-- DRIVER APPLICATION / APPROVAL
-- =====================================================

INSERT INTO DRIVER_APPLICATION
(application_id, driver_id, sponsor_id,
 decided_by_user_id, status, reason)
VALUES
(900001, 900003, 900001,
 NULL, 'PENDING', 'Test sponsor application');

UPDATE DRIVER_APPLICATION
SET status = 'APPROVED',
    decided_by_user_id = 900002,
    decision_at = CURRENT_TIMESTAMP,
    reason = 'Test application approved'
WHERE application_id = 900001;

UPDATE DRIVER
SET sponsor_id = 900001,
    participation_status = 'ACTIVE'
WHERE driver_id = 900003;


-- =====================================================
-- POINTS
-- =====================================================

UPDATE DRIVER
SET current_points = 1000
WHERE driver_id = 900003;

INSERT INTO POINT_TRANSACTION
(point_transaction_id, driver_id, sponsor_id,
 performed_by_user_id, points_delta, balance_after, reason)
VALUES
(900001, 900003, 900001,
 900002, 1000, 1000, 'Test safe-driving award');


-- Recurring points
INSERT INTO RECURRING_POINT_SCHEDULE
(schedule_id, driver_id, sponsor_id,
 created_by_user_id, points_amount,
 reason, frequency, next_run_at, is_active)
VALUES
(900001, 900003, 900001,
 900002, 100,
 'Monthly safe-driving award',
 'MONTHLY',
 DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 1 MONTH),
 TRUE);


-- =====================================================
-- PRODUCT / CATALOG
-- =====================================================

INSERT INTO PRODUCT
(product_id, api_source, external_product_id,
 product_name, description, dollar_price,
 availability, image_url, category, last_refreshed_at)
VALUES
(900001, 'TEST_API', 'TEST-PRODUCT-001',
 'Test Gift Card',
 'Test product for Team02 database',
 5.00, 'AVAILABLE', NULL, 'Rewards',
 CURRENT_TIMESTAMP);

INSERT INTO CATALOG_ITEM
(sponsor_id, product_id, point_price, is_active)
VALUES
(900001, 900001, 500, TRUE);


-- =====================================================
-- SHOPPING CART
-- =====================================================

INSERT INTO SHOPPING_CART
(cart_id, driver_id, sponsor_id, status)
VALUES
(900001, 900003, 900001, 'ACTIVE');

INSERT INTO CART_ITEM
(cart_id, sponsor_id, product_id,
 quantity, point_price_snapshot)
VALUES
(900001, 900001, 900001, 1, 500);


-- =====================================================
-- ORDER
-- =====================================================

INSERT INTO CUSTOMER_ORDER
(order_id, driver_id, sponsor_id,
 placed_by_user_id, status,
 total_points, total_dollar_amount)
VALUES
(900001, 900003, 900001,
 900003, 'PLACED', 500, 5.00);

INSERT INTO ORDER_ITEM
(order_id, line_number, sponsor_id,
 product_id, quantity,
 unit_point_price, unit_dollar_price)
VALUES
(900001, 1, 900001,
 900001, 1, 500, 5.00);

UPDATE SHOPPING_CART
SET status = 'CHECKED_OUT'
WHERE cart_id = 900001;

UPDATE DRIVER
SET current_points = 500
WHERE driver_id = 900003;

INSERT INTO POINT_TRANSACTION
(point_transaction_id, driver_id, sponsor_id,
 performed_by_user_id, points_delta,
 balance_after, reason)
VALUES
(900002, 900003, 900001,
 900003, -500, 500,
 'Test catalog purchase');


-- =====================================================
-- ALERTS / NOTIFICATION
-- =====================================================

INSERT INTO ALERT_PREFERENCE
(user_id, point_change_enabled,
 order_summary_enabled, drop_alert_enabled)
VALUES
(900003, TRUE, TRUE, TRUE);

INSERT INTO NOTIFICATION
(notification_id, user_id,
 notification_type, message, is_read)
VALUES
(900001, 900003,
 'ORDER',
 'Your test order was placed successfully.',
 FALSE);


-- =====================================================
-- AUDIT EVENT
-- =====================================================

INSERT INTO AUDIT_EVENT
(audit_event_id, actor_user_id,
 sponsor_id, driver_id,
 category, subject_username,
 entity_type, entity_id,
 success, reason_or_details)
VALUES
(900001, 900002,
 900001, 900003,
 'APPLICATION',
 'testdriver',
 'DRIVER_APPLICATION',
 900001,
 TRUE,
 'Test application approved');


-- =====================================================
-- ABOUT RELEASE
-- =====================================================

INSERT INTO ABOUT_RELEASE
(release_id, team_number, version_number,
 release_date, product_name, product_description)
VALUES
(900001, 2, '1.0',
 CURRENT_DATE,
 'Good Driver Incentive Program',
 'Team 02 test release');
