-- Team 02 - Good Driver Incentive Program
-- DEMO DATA for the final demo (Demo Guidance-F26): 2 sponsor organizations, 2 sponsor users and 2+ drivers
-- per organization, 2 admins, open driver applications to accept and reject, plus point history, catalog items,
-- orders, and schedules so reports have something to show.
--
-- Run ONCE after schema.sql (it does not depend on seed_test_data.sql). IDs are in the 910000 range so they
-- don't collide with the test seed. Every account gets the placeholder hash 'TEST_HASH_ONLY', which can't be
-- logged into; then, from backend/, run:
--     python scripts/set_test_passwords.py "<demo password>"
-- to give every placeholder account a real password. Don't commit the password (this repo is public).
--
-- Workbench: auto-commit is OFF there, so run COMMIT; afterwards.

-- =====================================================
-- ACCOUNTS
-- =====================================================

INSERT INTO USER_ACCOUNT (user_id, username, password_hash, first_name, last_name, email, phone, account_status) VALUES
-- admins
(910001, 'demoadmin1',   'TEST_HASH_ONLY', 'Avery',  'Collins',  'demoadmin1@example.com',   '864-555-0101', 'ACTIVE'),
(910002, 'demoadmin2',   'TEST_HASH_ONLY', 'Jordan', 'Mitchell', 'demoadmin2@example.com',   '864-555-0102', 'ACTIVE'),
-- Palmetto Freight Lines sponsor users
(910011, 'pfl_sponsor1', 'TEST_HASH_ONLY', 'Rachel', 'Greene',   'rgreene@example.com',      '864-555-0111', 'ACTIVE'),
(910012, 'pfl_sponsor2', 'TEST_HASH_ONLY', 'Owen',   'Patel',    'opatel@example.com',       '864-555-0112', 'ACTIVE'),
-- Blue Ridge Haulers sponsor users
(910013, 'brh_sponsor1', 'TEST_HASH_ONLY', 'Lena',   'Ward',     'lward@example.com',        '828-555-0113', 'ACTIVE'),
(910014, 'brh_sponsor2', 'TEST_HASH_ONLY', 'Victor', 'Nguyen',   'vnguyen@example.com',      '828-555-0114', 'ACTIVE'),
-- drivers already in programs
(910021, 'demodriver1',  'TEST_HASH_ONLY', 'Marcus', 'Hill',     'mhill@example.com',        '864-555-0121', 'ACTIVE'),
(910022, 'demodriver2',  'TEST_HASH_ONLY', 'Ana',    'Lopez',    'alopez@example.com',       '864-555-0122', 'ACTIVE'),
(910023, 'demodriver3',  'TEST_HASH_ONLY', 'Jake',   'Turner',   'jturner@example.com',      '828-555-0123', 'ACTIVE'),
(910024, 'demodriver4',  'TEST_HASH_ONLY', 'Priya',  'Shah',     'pshah@example.com',        '828-555-0124', 'ACTIVE'),
-- applicants with open applications
(910031, 'applicant1',   'TEST_HASH_ONLY', 'Dana',   'Brooks',   'dbrooks@example.com',      '864-555-0131', 'ACTIVE'),
(910032, 'applicant2',   'TEST_HASH_ONLY', 'Tyler',  'Reed',     'treed@example.com',        '864-555-0132', 'ACTIVE'),
(910033, 'applicant3',   'TEST_HASH_ONLY', 'Sam',    'Ortiz',    'sortiz@example.com',       '828-555-0133', 'ACTIVE');

INSERT INTO ADMIN (admin_id) VALUES (910001), (910002);

INSERT INTO SPONSOR_ORGANIZATION (sponsor_id, sponsor_name, status, point_dollar_rate, contact_email, phone) VALUES
(910001, 'Palmetto Freight Lines', 'ACTIVE', 0.01, 'rewards@palmettofreight.example.com', '864-555-1000'),
(910002, 'Blue Ridge Haulers',     'ACTIVE', 0.02, 'drivers@blueridgehaulers.example.com', '828-555-2000');

INSERT INTO SPONSOR_USER (sponsor_user_id, sponsor_id, job_title) VALUES
(910011, 910001, 'Safety Manager'),
(910012, 910001, 'Fleet Coordinator'),
(910013, 910002, 'Driver Programs Lead'),
(910014, 910002, 'Operations Manager');

-- DRIVER keeps the legacy single-sponsor columns; DRIVER_SPONSOR is authoritative.
INSERT INTO DRIVER (driver_id, sponsor_id, current_points, participation_status) VALUES
(910021, 910001, 3500, 'ACTIVE'),
(910022, 910001, 2500, 'ACTIVE'),
(910023, 910002, 1550, 'ACTIVE'),
(910024, 910002, 1300, 'ACTIVE'),
(910031, NULL, 0, 'APPLICANT'),
(910032, NULL, 0, 'APPLICANT'),
(910033, NULL, 0, 'APPLICANT');

-- Ana Lopez (910022) drives for both sponsors (RC#2 multiple sponsors).
INSERT INTO DRIVER_SPONSOR (driver_id, sponsor_id, current_points, participation_status, joined_at) VALUES
(910021, 910001, 3500, 'ACTIVE', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 60 DAY)),
(910022, 910001, 2500, 'ACTIVE', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 45 DAY)),
(910022, 910002,  600, 'ACTIVE', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 10 DAY)),
(910023, 910002, 1550, 'ACTIVE', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 50 DAY)),
(910024, 910002, 1300, 'ACTIVE', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 30 DAY));

INSERT INTO ALERT_PREFERENCE (user_id, point_change_enabled, order_summary_enabled, drop_alert_enabled) VALUES
(910021, TRUE, TRUE, TRUE), (910022, TRUE, TRUE, TRUE), (910023, TRUE, TRUE, TRUE), (910024, TRUE, FALSE, TRUE),
(910031, TRUE, TRUE, TRUE), (910032, TRUE, TRUE, TRUE), (910033, TRUE, TRUE, TRUE);

-- =====================================================
-- APPLICATIONS (3 open: accept Dana, reject Tyler, Sam is for Blue Ridge)
-- =====================================================

INSERT INTO DRIVER_APPLICATION
(application_id, driver_id, sponsor_id, decided_by_user_id, submitted_at, status, decision_at, reason,
 cdl_number, cdl_state, years_experience, applicant_notes) VALUES
(910001, 910021, 910001, 910011, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 61 DAY), 'APPROVED', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 60 DAY),
 'Clean record', 'SC1234567', 'SC', 8, 'Regional routes out of Greenville.'),
(910002, 910022, 910001, 910012, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 46 DAY), 'APPROVED', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 45 DAY),
 'Welcome aboard', 'SC7654321', 'SC', 5, NULL),
(910003, 910022, 910002, 910013, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 11 DAY), 'APPROVED', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 10 DAY),
 'Approved for weekend loads', 'SC7654321', 'SC', 5, 'Weekend runs only.'),
(910004, 910023, 910002, 910013, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 51 DAY), 'APPROVED', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 50 DAY),
 'Experienced long-haul driver', 'NC2223334', 'NC', 12, NULL),
(910005, 910024, 910002, 910014, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 31 DAY), 'APPROVED', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 30 DAY),
 'Approved', 'NC5556667', 'NC', 3, NULL),
(910006, 910031, 910001, NULL, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 2 DAY), 'PENDING', NULL, NULL,
 'SC9081726', 'SC', 6, 'Six years flatbed, no violations. Looking for a safety-focused program.'),
(910007, 910032, 910001, NULL, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 1 DAY), 'PENDING', NULL, NULL,
 'GA1029384', 'GA', 1, 'New CDL holder.'),
(910008, 910033, 910002, NULL, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 3 DAY), 'PENDING', NULL, NULL,
 'NC4455667', 'NC', 4, 'Interested in Blue Ridge regional routes.');

-- =====================================================
-- POINTS (balance_after matches DRIVER_SPONSOR.current_points above)
-- Purchases / refunds say "purchase" / "Refund" so reports can tell them from sponsor awards.
-- =====================================================

INSERT INTO POINT_TRANSACTION (driver_id, sponsor_id, performed_by_user_id, points_delta, balance_after, reason, created_at) VALUES
(910021, 910001, 910011,  5000, 5000, 'Welcome bonus',                         DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 60 DAY)),
(910021, 910001, 910011,  1500, 6500, '30 days of on-time deliveries',         DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 30 DAY)),
(910021, 910001, 910012,  -500, 6000, 'Late log submission',                   DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 20 DAY)),
(910021, 910001, 910021, -2500, 3500, 'Catalog purchase, order #910001',       DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 14 DAY)),
(910022, 910001, 910012,  3000, 3000, 'Welcome bonus',                         DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 45 DAY)),
(910022, 910001, 910011,  1000, 4000, 'Clean roadside inspection',             DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 25 DAY)),
(910022, 910001, 910022, -2000, 2000, 'Catalog purchase, order #910003',       DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 9 DAY)),
(910022, 910001, 910011,  2000, 4000, 'Refund for cancelled order #910003',    DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 8 DAY)),
(910022, 910001, 910022, -1500, 2500, 'Catalog purchase, order #910002',       DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 3 DAY)),
(910022, 910002, 910013,   600,  600, 'Welcome bonus',                         DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 10 DAY)),
(910023, 910002, 910013,  2000, 2000, 'Welcome bonus',                         DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 50 DAY)),
(910023, 910002, 910014,   800, 2800, 'Zero hard-braking events this month',   DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 22 DAY)),
(910023, 910002, 910023, -1250, 1550, 'Catalog purchase, order #910004',       DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 6 DAY)),
(910024, 910002, 910014,  1500, 1500, 'Welcome bonus',                         DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 30 DAY)),
(910024, 910002, 910013,  -200, 1300, 'Speeding alert on I-40',                DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 12 DAY));

INSERT INTO RECURRING_POINT_SCHEDULE
(driver_id, sponsor_id, created_by_user_id, points_amount, reason, frequency, next_run_at, is_active) VALUES
(910021, 910001, 910011, 250, 'Weekly safe-driving bonus',  'WEEKLY',  DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 3 DAY), TRUE),
(910023, 910002, 910013, 500, 'Monthly clean-record bonus', 'MONTHLY', DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 12 DAY), TRUE);

-- =====================================================
-- CATALOG (non-eBay demo products; sponsors can add real eBay items from the Catalog page)
-- point price = dollar price / point_dollar_rate
-- =====================================================

INSERT INTO PRODUCT (product_id, api_source, external_product_id, product_name, description, dollar_price,
                     availability, image_url, category, last_refreshed_at) VALUES
(910001, 'DEMO', 'DEMO-HEADSET',  'Wireless Bluetooth Trucker Headset', 'Noise-canceling headset with a boom mic for hands-free calls.', 25.00, 'AVAILABLE', NULL, 'Electronics', CURRENT_TIMESTAMP),
(910002, 'DEMO', 'DEMO-MUG',      'Insulated Travel Mug, 20 oz',        'Keeps coffee hot for 12 hours. Fits most cab cup holders.',      15.00, 'AVAILABLE', NULL, 'Kitchen',     CURRENT_TIMESTAMP),
(910003, 'DEMO', 'DEMO-GIFTCARD', 'Truck Stop Gift Card, $20',          'Good for fuel, food, and showers at participating stops.',       20.00, 'AVAILABLE', NULL, 'Gift cards',  CURRENT_TIMESTAMP),
(910004, 'DEMO', 'DEMO-CUSHION',  '12V Heated Seat Cushion',            'Plugs into the cab outlet. Three heat settings.',                35.00, 'AVAILABLE', NULL, 'Comfort',     CURRENT_TIMESTAMP);

INSERT INTO CATALOG_ITEM (sponsor_id, product_id, point_price, is_active) VALUES
(910001, 910001, 2500, TRUE), (910001, 910002, 1500, TRUE), (910001, 910003, 2000, TRUE), (910001, 910004, 3500, TRUE),
(910002, 910001, 1250, TRUE), (910002, 910003, 1000, TRUE), (910002, 910004, 1750, TRUE);

-- =====================================================
-- ORDERS (one each: delivered, placed, cancelled + refunded, shipped)
-- =====================================================

INSERT INTO CUSTOMER_ORDER (order_id, driver_id, sponsor_id, placed_by_user_id, status, total_points,
                            total_dollar_amount, placed_at, cancelled_at) VALUES
(910001, 910021, 910001, 910021, 'DELIVERED', 2500, 25.00, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 14 DAY), NULL),
(910002, 910022, 910001, 910022, 'PLACED',    1500, 15.00, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 3 DAY),  NULL),
(910003, 910022, 910001, 910022, 'CANCELLED', 2000, 20.00, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 9 DAY),  DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 8 DAY)),
(910004, 910023, 910002, 910023, 'SHIPPED',   1250, 25.00, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 6 DAY),  NULL);

INSERT INTO ORDER_ITEM (order_id, line_number, sponsor_id, product_id, quantity, unit_point_price, unit_dollar_price) VALUES
(910001, 1, 910001, 910001, 1, 2500, 25.00),
(910002, 1, 910001, 910002, 1, 1500, 15.00),
(910003, 1, 910001, 910003, 1, 2000, 20.00),
(910004, 1, 910002, 910001, 1, 1250, 25.00);

-- =====================================================
-- NOTIFICATIONS
-- =====================================================

INSERT INTO NOTIFICATION (user_id, notification_type, message, is_read, created_at) VALUES
(910021, 'POINT_CHANGE', '1,500 points were added by Palmetto Freight Lines: 30 days of on-time deliveries. New balance: 6,500.', TRUE,  DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 30 DAY)),
(910021, 'POINT_CHANGE', '500 points were deducted by Palmetto Freight Lines: Late log submission. New balance: 6,000.',         FALSE, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 20 DAY)),
(910021, 'ORDER',        'Order #910001 was placed: Wireless Bluetooth Trucker Headset for 2,500 points.',                     FALSE, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 14 DAY)),
(910022, 'ORDER',        'Order #910003 was cancelled and 2,000 points were refunded.',                                          FALSE, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 8 DAY)),
(910023, 'ORDER',        'Order #910004 has shipped.',                                                                           FALSE, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 4 DAY)),
(910024, 'POINT_CHANGE', '200 points were deducted by Blue Ridge Haulers: Speeding alert on I-40. New balance: 1,300.',         FALSE, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 12 DAY));

-- =====================================================
-- AUDIT HISTORY (the app adds more as it's used)
-- =====================================================

INSERT INTO AUDIT_EVENT (actor_user_id, sponsor_id, driver_id, category, subject_username, entity_type, entity_id,
                         success, reason_or_details, created_at) VALUES
(910001, 910001, NULL, 'ACCOUNT', 'Palmetto Freight Lines', 'SPONSOR_ORGANIZATION', 910001, TRUE, 'Created sponsor Palmetto Freight Lines (1 point = $0.01)', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 70 DAY)),
(910001, 910002, NULL, 'ACCOUNT', 'Blue Ridge Haulers',     'SPONSOR_ORGANIZATION', 910002, TRUE, 'Created sponsor Blue Ridge Haulers (1 point = $0.02)',     DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 70 DAY)),
(910011, 910001, 910021, 'APPLICATION', 'demodriver1', 'DRIVER_APPLICATION', 910001, TRUE, 'Application approved: Clean record', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 60 DAY)),
(910011, 910001, 910021, 'POINT_CHANGE', 'demodriver1', 'POINT_TRANSACTION', NULL, TRUE, '30 days of on-time deliveries (+1500)', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 30 DAY)),
(910012, 910001, 910021, 'POINT_CHANGE', 'demodriver1', 'POINT_TRANSACTION', NULL, TRUE, 'Late log submission (-500)',            DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 20 DAY)),
(NULL, NULL, NULL, 'LOGIN', 'demodriver2', 'USER_ACCOUNT', 910022, FALSE, 'Failed login: wrong password', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 5 DAY)),
(910022, NULL, 910022, 'LOGIN', 'demodriver2', 'USER_ACCOUNT', 910022, TRUE, 'Signed in', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 5 DAY)),
(910011, 910001, 910022, 'ORDER', 'demodriver2', 'CUSTOMER_ORDER', 910003, TRUE, 'Cancelled order #910003 and refunded 2,000 points', DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 8 DAY));
