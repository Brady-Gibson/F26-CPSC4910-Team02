-- Team 02 - Good Driver Incentive Program
-- Migration 001: applicant details on DRIVER_APPLICATION
-- Story: "Required Information" (Driver Sponsor Application, Sprint 3)
--
-- Adds the information a driver fills out when applying to a sponsor.
-- Columns are NULL-able so existing rows (like the seed data) still load.
-- The Flask route makes them required for every NEW application.
--
-- Run once against Team02_DB after schema.sql.

USE Team02_DB;

ALTER TABLE DRIVER_APPLICATION
    ADD COLUMN cdl_number        VARCHAR(30)  NULL AFTER reason,
    ADD COLUMN cdl_state         CHAR(2)      NULL AFTER cdl_number,
    ADD COLUMN years_experience  INT          NULL AFTER cdl_state,
    ADD COLUMN applicant_notes   VARCHAR(500) NULL AFTER years_experience;

-- Speeds up "does this driver already have a pending application?"
CREATE INDEX idx_application_driver_status
    ON DRIVER_APPLICATION (driver_id, status);
