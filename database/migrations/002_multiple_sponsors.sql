-- RC#2: upgrade an existing schema after migration 001.
-- Run once, with application writes paused and a verified backup.
-- This is NOT compatible with the old single-sponsor backend.
-- All checks execute before data/schema changes. A SIGNAL stops the procedure.
-- MySQL DDL auto-commits: restore the backup if a later DDL operation fails.
USE Team02_DB;

DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_rc2$$
CREATE PROCEDURE migrate_rc2()
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'DRIVER_SPONSOR') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'RC2 already applied or partially applied; inspect before retrying';
    END IF;
    IF EXISTS (SELECT 1 FROM DRIVER WHERE current_points < 0 OR (sponsor_id IS NULL AND current_points <> 0)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Resolve negative or unassigned legacy balances before RC2';
    END IF;
    IF EXISTS (SELECT 1 FROM DRIVER_APPLICATION WHERE status = 'PENDING' GROUP BY driver_id, sponsor_id HAVING COUNT(*) > 1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Resolve duplicate pending applications for the same sponsor';
    END IF;
    IF EXISTS (SELECT 1 FROM SHOPPING_CART WHERE status = 'ACTIVE' GROUP BY driver_id, sponsor_id HAVING COUNT(*) > 1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Resolve duplicate active carts for the same sponsor';
    END IF;
    IF EXISTS (SELECT 1 FROM CART_ITEM i JOIN SHOPPING_CART c ON c.cart_id=i.cart_id WHERE i.sponsor_id<>c.sponsor_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Resolve cross-sponsor cart items before RC2';
    END IF;
    IF EXISTS (SELECT 1 FROM ORDER_ITEM i JOIN CUSTOMER_ORDER o ON o.order_id=i.order_id WHERE i.sponsor_id<>o.sponsor_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Resolve cross-sponsor order items before RC2';
    END IF;
    IF EXISTS (SELECT 1 FROM POINT_TRANSACTION x JOIN DRIVER d ON d.driver_id=x.driver_id WHERE d.sponsor_id IS NULL OR d.sponsor_id<>x.sponsor_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Reconcile historical sponsor relationships in POINT_TRANSACTION before RC2';
    END IF;
    IF EXISTS (SELECT 1 FROM RECURRING_POINT_SCHEDULE x JOIN DRIVER d ON d.driver_id=x.driver_id WHERE d.sponsor_id IS NULL OR d.sponsor_id<>x.sponsor_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Reconcile historical sponsor relationships in RECURRING_POINT_SCHEDULE before RC2';
    END IF;
    IF EXISTS (SELECT 1 FROM SHOPPING_CART x JOIN DRIVER d ON d.driver_id=x.driver_id WHERE d.sponsor_id IS NULL OR d.sponsor_id<>x.sponsor_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Reconcile historical sponsor relationships in SHOPPING_CART before RC2';
    END IF;
    IF EXISTS (SELECT 1 FROM CUSTOMER_ORDER x JOIN DRIVER d ON d.driver_id=x.driver_id WHERE d.sponsor_id IS NULL OR d.sponsor_id<>x.sponsor_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Reconcile historical sponsor relationships in CUSTOMER_ORDER before RC2';
    END IF;

    CREATE TABLE DRIVER_SPONSOR (
        driver_id INT NOT NULL,
        sponsor_id INT NOT NULL,
        current_points BIGINT NOT NULL DEFAULT 0,
        participation_status VARCHAR(20) NOT NULL,
        joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (driver_id, sponsor_id),
        INDEX idx_membership_sponsor_status (sponsor_id, participation_status),
        CONSTRAINT fk_membership_driver FOREIGN KEY (driver_id) REFERENCES DRIVER(driver_id),
        CONSTRAINT fk_membership_sponsor FOREIGN KEY (sponsor_id) REFERENCES SPONSOR_ORGANIZATION(sponsor_id),
        CONSTRAINT chk_membership_balance CHECK (current_points >= 0)
    );
    INSERT INTO DRIVER_SPONSOR
        (driver_id, sponsor_id, current_points, participation_status, joined_at)
    SELECT driver_id, sponsor_id, current_points, participation_status, joined_at
    FROM DRIVER WHERE sponsor_id IS NOT NULL;

    ALTER TABLE DRIVER_APPLICATION
        ADD COLUMN pending_sponsor_id INT GENERATED ALWAYS AS
            (CASE WHEN status = 'PENDING' THEN sponsor_id ELSE NULL END) STORED,
        ADD UNIQUE KEY uq_pending_application (driver_id, pending_sponsor_id);
    ALTER TABLE SHOPPING_CART
        ADD COLUMN active_sponsor_id INT GENERATED ALWAYS AS
            (CASE WHEN status = 'ACTIVE' THEN sponsor_id ELSE NULL END) STORED,
        ADD UNIQUE KEY uq_active_cart (driver_id, active_sponsor_id),
        ADD UNIQUE KEY uq_cart_sponsor (cart_id, sponsor_id);
    ALTER TABLE CUSTOMER_ORDER ADD UNIQUE KEY uq_order_sponsor (order_id, sponsor_id);
    ALTER TABLE CART_ITEM DROP FOREIGN KEY fk_cart_item_cart,
        ADD CONSTRAINT fk_cart_item_cart_sponsor FOREIGN KEY (cart_id, sponsor_id)
            REFERENCES SHOPPING_CART(cart_id, sponsor_id);
    ALTER TABLE ORDER_ITEM DROP FOREIGN KEY fk_order_item_order,
        ADD CONSTRAINT fk_order_item_order_sponsor FOREIGN KEY (order_id, sponsor_id)
            REFERENCES CUSTOMER_ORDER(order_id, sponsor_id);
    ALTER TABLE POINT_TRANSACTION ADD CONSTRAINT fk_point_membership
        FOREIGN KEY (driver_id, sponsor_id) REFERENCES DRIVER_SPONSOR(driver_id, sponsor_id);
    ALTER TABLE RECURRING_POINT_SCHEDULE ADD CONSTRAINT fk_schedule_membership
        FOREIGN KEY (driver_id, sponsor_id) REFERENCES DRIVER_SPONSOR(driver_id, sponsor_id);
    ALTER TABLE SHOPPING_CART ADD CONSTRAINT fk_cart_membership
        FOREIGN KEY (driver_id, sponsor_id) REFERENCES DRIVER_SPONSOR(driver_id, sponsor_id);
    ALTER TABLE CUSTOMER_ORDER ADD CONSTRAINT fk_order_membership
        FOREIGN KEY (driver_id, sponsor_id) REFERENCES DRIVER_SPONSOR(driver_id, sponsor_id);
END$$
CALL migrate_rc2()$$
DROP PROCEDURE migrate_rc2$$
DELIMITER ;
