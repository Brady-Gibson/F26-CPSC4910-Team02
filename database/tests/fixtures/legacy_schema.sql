-- Team 02 - Good Driver Incentive Program
-- Database Schema
-- MySQL / AWS RDS

USE Team02_DB;


-- =====================================================
-- USER ACCOUNT
-- =====================================================

CREATE TABLE USER_ACCOUNT (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    phone VARCHAR(20),
    account_status VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
);


-- =====================================================
-- ADMIN
-- =====================================================

CREATE TABLE ADMIN (
    admin_id INT PRIMARY KEY,

    CONSTRAINT fk_admin_user
        FOREIGN KEY (admin_id)
        REFERENCES USER_ACCOUNT(user_id)
);


-- =====================================================
-- SPONSOR ORGANIZATION
-- =====================================================

CREATE TABLE SPONSOR_ORGANIZATION (
    sponsor_id INT AUTO_INCREMENT PRIMARY KEY,
    sponsor_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    point_dollar_rate DECIMAL(10,2) NOT NULL,
    contact_email VARCHAR(100),
    phone VARCHAR(20),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- =====================================================
-- SPONSOR USER
-- =====================================================

CREATE TABLE SPONSOR_USER (
    sponsor_user_id INT PRIMARY KEY,
    sponsor_id INT NOT NULL,
    job_title VARCHAR(100),

    CONSTRAINT fk_sponsor_user_account
        FOREIGN KEY (sponsor_user_id)
        REFERENCES USER_ACCOUNT(user_id),

    CONSTRAINT fk_sponsor_user_sponsor
        FOREIGN KEY (sponsor_id)
        REFERENCES SPONSOR_ORGANIZATION(sponsor_id)
);


-- =====================================================
-- DRIVER
-- =====================================================

CREATE TABLE DRIVER (
    driver_id INT PRIMARY KEY,
    sponsor_id INT NULL,
    current_points BIGINT NOT NULL DEFAULT 0,
    participation_status VARCHAR(20) NOT NULL,
    joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_driver_user
        FOREIGN KEY (driver_id)
        REFERENCES USER_ACCOUNT(user_id),

    CONSTRAINT fk_driver_sponsor
        FOREIGN KEY (sponsor_id)
        REFERENCES SPONSOR_ORGANIZATION(sponsor_id)
);


-- =====================================================
-- DRIVER APPLICATION
-- =====================================================

CREATE TABLE DRIVER_APPLICATION (
    application_id INT AUTO_INCREMENT PRIMARY KEY,
    driver_id INT NOT NULL,
    sponsor_id INT NOT NULL,
    decided_by_user_id INT NULL,
    submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL,
    decision_at DATETIME NULL,
    reason VARCHAR(500),

    CONSTRAINT fk_application_driver
        FOREIGN KEY (driver_id)
        REFERENCES DRIVER(driver_id),

    CONSTRAINT fk_application_sponsor
        FOREIGN KEY (sponsor_id)
        REFERENCES SPONSOR_ORGANIZATION(sponsor_id),

    CONSTRAINT fk_application_decided_by
        FOREIGN KEY (decided_by_user_id)
        REFERENCES USER_ACCOUNT(user_id)
);


-- =====================================================
-- POINT TRANSACTION
-- =====================================================

CREATE TABLE POINT_TRANSACTION (
    point_transaction_id INT AUTO_INCREMENT PRIMARY KEY,
    driver_id INT NOT NULL,
    sponsor_id INT NOT NULL,
    performed_by_user_id INT NULL,
    points_delta BIGINT NOT NULL,
    balance_after BIGINT NOT NULL,
    reason VARCHAR(500) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_point_driver
        FOREIGN KEY (driver_id)
        REFERENCES DRIVER(driver_id),

    CONSTRAINT fk_point_sponsor
        FOREIGN KEY (sponsor_id)
        REFERENCES SPONSOR_ORGANIZATION(sponsor_id),

    CONSTRAINT fk_point_performed_by
        FOREIGN KEY (performed_by_user_id)
        REFERENCES USER_ACCOUNT(user_id)
);


-- =====================================================
-- RECURRING POINT SCHEDULE
-- =====================================================

CREATE TABLE RECURRING_POINT_SCHEDULE (
    schedule_id INT AUTO_INCREMENT PRIMARY KEY,
    driver_id INT NOT NULL,
    sponsor_id INT NOT NULL,
    created_by_user_id INT NOT NULL,
    points_amount BIGINT NOT NULL,
    reason VARCHAR(500),
    frequency VARCHAR(30) NOT NULL,
    next_run_at DATETIME,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT fk_schedule_driver
        FOREIGN KEY (driver_id)
        REFERENCES DRIVER(driver_id),

    CONSTRAINT fk_schedule_sponsor
        FOREIGN KEY (sponsor_id)
        REFERENCES SPONSOR_ORGANIZATION(sponsor_id),

    CONSTRAINT fk_schedule_created_by
        FOREIGN KEY (created_by_user_id)
        REFERENCES USER_ACCOUNT(user_id)
);


-- =====================================================
-- AUDIT EVENT
-- =====================================================

CREATE TABLE AUDIT_EVENT (
    audit_event_id INT AUTO_INCREMENT PRIMARY KEY,
    actor_user_id INT NULL,
    sponsor_id INT NULL,
    driver_id INT NULL,
    category VARCHAR(50) NOT NULL,
    subject_username VARCHAR(100),
    entity_type VARCHAR(50),
    entity_id INT,
    success BOOLEAN NOT NULL,
    reason_or_details VARCHAR(500),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_audit_actor
        FOREIGN KEY (actor_user_id)
        REFERENCES USER_ACCOUNT(user_id),

    CONSTRAINT fk_audit_sponsor
        FOREIGN KEY (sponsor_id)
        REFERENCES SPONSOR_ORGANIZATION(sponsor_id),

    CONSTRAINT fk_audit_driver
        FOREIGN KEY (driver_id)
        REFERENCES DRIVER(driver_id)
);


-- =====================================================
-- PRODUCT
-- =====================================================

CREATE TABLE PRODUCT (
    product_id INT AUTO_INCREMENT PRIMARY KEY,
    api_source VARCHAR(50),
    external_product_id VARCHAR(200) UNIQUE,
    product_name VARCHAR(255) NOT NULL,
    description TEXT,
    dollar_price DECIMAL(12,2),
    availability VARCHAR(50),
    image_url VARCHAR(1000),
    category VARCHAR(100),
    last_refreshed_at DATETIME
);


-- =====================================================
-- CATALOG ITEM
-- =====================================================

CREATE TABLE CATALOG_ITEM (
    sponsor_id INT NOT NULL,
    product_id INT NOT NULL,
    point_price BIGINT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (sponsor_id, product_id),

    CONSTRAINT fk_catalog_sponsor
        FOREIGN KEY (sponsor_id)
        REFERENCES SPONSOR_ORGANIZATION(sponsor_id),

    CONSTRAINT fk_catalog_product
        FOREIGN KEY (product_id)
        REFERENCES PRODUCT(product_id)
);


-- =====================================================
-- SHOPPING CART
-- =====================================================

CREATE TABLE SHOPPING_CART (
    cart_id INT AUTO_INCREMENT PRIMARY KEY,
    driver_id INT NOT NULL,
    sponsor_id INT NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_cart_driver
        FOREIGN KEY (driver_id)
        REFERENCES DRIVER(driver_id),

    CONSTRAINT fk_cart_sponsor
        FOREIGN KEY (sponsor_id)
        REFERENCES SPONSOR_ORGANIZATION(sponsor_id)
);


-- =====================================================
-- CART ITEM
-- =====================================================

CREATE TABLE CART_ITEM (
    cart_id INT NOT NULL,
    sponsor_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    point_price_snapshot BIGINT NOT NULL,

    PRIMARY KEY (cart_id, sponsor_id, product_id),

    CONSTRAINT fk_cart_item_cart
        FOREIGN KEY (cart_id)
        REFERENCES SHOPPING_CART(cart_id),

    CONSTRAINT fk_cart_item_catalog
        FOREIGN KEY (sponsor_id, product_id)
        REFERENCES CATALOG_ITEM(sponsor_id, product_id)
);


-- =====================================================
-- CUSTOMER ORDER
-- =====================================================

CREATE TABLE CUSTOMER_ORDER (
    order_id INT AUTO_INCREMENT PRIMARY KEY,
    driver_id INT NOT NULL,
    sponsor_id INT NOT NULL,
    placed_by_user_id INT NOT NULL,
    status VARCHAR(30) NOT NULL,
    total_points BIGINT NOT NULL,
    total_dollar_amount DECIMAL(12,2),
    placed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cancelled_at DATETIME NULL,

    CONSTRAINT fk_order_driver
        FOREIGN KEY (driver_id)
        REFERENCES DRIVER(driver_id),

    CONSTRAINT fk_order_sponsor
        FOREIGN KEY (sponsor_id)
        REFERENCES SPONSOR_ORGANIZATION(sponsor_id),

    CONSTRAINT fk_order_placed_by
        FOREIGN KEY (placed_by_user_id)
        REFERENCES USER_ACCOUNT(user_id)
);


-- =====================================================
-- ORDER ITEM
-- =====================================================

CREATE TABLE ORDER_ITEM (
    order_id INT NOT NULL,
    line_number INT NOT NULL,
    sponsor_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    unit_point_price BIGINT NOT NULL,
    unit_dollar_price DECIMAL(12,2),

    PRIMARY KEY (order_id, line_number),

    CONSTRAINT fk_order_item_order
        FOREIGN KEY (order_id)
        REFERENCES CUSTOMER_ORDER(order_id),

    CONSTRAINT fk_order_item_catalog
        FOREIGN KEY (sponsor_id, product_id)
        REFERENCES CATALOG_ITEM(sponsor_id, product_id)
);


-- =====================================================
-- NOTIFICATION
-- =====================================================

CREATE TABLE NOTIFICATION (
    notification_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    notification_type VARCHAR(40) NOT NULL,
    message TEXT NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_notification_user
        FOREIGN KEY (user_id)
        REFERENCES USER_ACCOUNT(user_id)
);


-- =====================================================
-- ALERT PREFERENCE
-- =====================================================

CREATE TABLE ALERT_PREFERENCE (
    user_id INT PRIMARY KEY,
    point_change_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    order_summary_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    drop_alert_enabled BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT fk_alert_preference_user
        FOREIGN KEY (user_id)
        REFERENCES USER_ACCOUNT(user_id)
);


-- =====================================================
-- ABOUT RELEASE
-- =====================================================

CREATE TABLE ABOUT_RELEASE (
    release_id INT AUTO_INCREMENT PRIMARY KEY,
    team_number INT NOT NULL,
    version_number VARCHAR(30) NOT NULL,
    release_date DATE NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    product_description TEXT
);
