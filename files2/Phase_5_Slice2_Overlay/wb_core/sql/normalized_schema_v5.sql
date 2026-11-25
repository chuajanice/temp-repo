-- =============================================================================
-- Water Billing System V4: normalized schema, REVISION 4 (v3 with money columns as DOUBLE, Phase 4A)
-- Derived from normalized_schema_v3.sql by wb_core/tools/generate_money_migration.py.
-- Revision 3 header follows:
-- Water Billing System V4: normalized schema, REVISION 3 (v2 + amendments A-1, A-3, A-5)
--
-- SUPERSEDES: proposed_schema_DRAFT_v2.sql. Amendments are listed in CHANGELOG.md.
--   A-1: legacy_* identifier columns that new rows do not have are NULLABLE (UNIQUE kept).
--   A-3: CREATE DATABASE / USE are kept for manual runs; the Django migration strips them.
--   A-5: barangay_monthly_summary gets a surrogate primary key; (barangay, year, month) is UNIQUE.
--   Requires MySQL 8.0.16 or later (CHECK constraints are enforced from 8.0.16).
--
-- STATUS:
--   * NOT EXECUTED against any database.
--   * NOT VALIDATED against a MySQL 8.0 server (none available in the drafting
--     environment). Validate in MySQL Workbench on an EMPTY scratch schema only.
--   * The legacy database `waterbillingv3` is not referenced or modified.
--   * Items marked DECISION need explicit approval before the schema is final.
--
-- PRINCIPLES (see PROPOSED_NORMALIZED_SCHEMA_v2.md):
--   * Every legacy row is preserved. Ambiguous or duplicate rows get
--     status 'pending_review' (or link_status 'ambiguous'/'unlinked') and an
--     entry in migration_exception. Nothing is deleted or guessed.
--   * "At most one active row" rules are enforced with generated columns.
--     Pending and superseded rows are excluded from the uniqueness rule, so
--     they can be stored without being deleted.
--   * Money is DECIMAL. Legacy DOUBLE values are rounded at migration time and
--     every difference is reported.
--   * Financial rows reference connections with RESTRICT. Nothing cascades.
--   * Tariff rules, penalty rules, and the allocation policy are data, so they
--     can be configured. Their default values reproduce current behaviour.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS waterbilling_v4
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_as_ci;     -- DECISION D-12: collation (see v2 proposal section 6)

USE waterbilling_v4;

-- -----------------------------------------------------------------------------
-- PREREQUISITE (not in this script): Django's custom user table index_systemusers
-- and the Django auth tables must be created FIRST, in this same database, with
-- the same character set and collation as every column that references
-- index_systemusers.username. MySQL rejects a foreign key between string
-- columns whose character set or collation differ.
-- -----------------------------------------------------------------------------

-- =============================================================================
-- 1. REFERENCE DATA
-- =============================================================================

CREATE TABLE barangay (
  barangay_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  legacy_barangay_id  BIGINT NULL,                  -- index_barangays.id
  name                VARCHAR(20) NOT NULL,             -- index_barangays.barangay (not unique in legacy)
  PRIMARY KEY (barangay_id),
  UNIQUE KEY uq_barangay_legacy (legacy_barangay_id)
) ENGINE=InnoDB;

CREATE TABLE consumer_type (
  consumer_type_code  VARCHAR(20) NOT NULL,             -- index_consumertype.contypeid (natural key, kept)
  name                VARCHAR(20) NOT NULL,             -- contype
  min_reading_m3      INT NOT NULL,                     -- minReading (pre-Oct-2024 linear tariff)
  min_reading_charge  DECIMAL(12,2) NOT NULL,           -- minReadingCharge
  rate_after_min      DECIMAL(12,2) NOT NULL,           -- rateAfterMin
  created_on          DATE NOT NULL,
  modified_on         DATE NOT NULL,
  created_by          VARCHAR(20) NULL,
  PRIMARY KEY (consumer_type_code),
  CONSTRAINT fk_consumer_type_user FOREIGN KEY (created_by)
    REFERENCES index_systemusers (username) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Tariff schedules. Each row is one tariff regime with an effective period.
-- The three regimes that the legacy code implements are seeded as DATA (not
-- code) by the migration, and are verified by recomputation (see mapping file).
CREATE TABLE tariff_schedule (
  tariff_schedule_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name                VARCHAR(100) NOT NULL,
  method              ENUM('consumer_type_linear','progressive_tiers') NOT NULL,
  effective_from      DATE NOT NULL,                    -- first day of the first billing period it applies to
  effective_to        DATE NULL,                        -- NULL = open-ended
  adjustment_factor   DECIMAL(6,4) NOT NULL DEFAULT 1.0000,  -- legacy 0.60 / 0.70 multiplier; 1.0 for linear
  source_note         VARCHAR(200) NULL,                -- e.g. 'bill_compute(), functions.py'
  PRIMARY KEY (tariff_schedule_id),
  CONSTRAINT chk_tariff_period CHECK (effective_to IS NULL OR effective_to > effective_from),
  KEY ix_tariff_effective (effective_from)
) ENGINE=InnoDB;

-- Progressive bands, used only when method = 'progressive_tiers'.
-- A band covers cubic metres from_m3 to to_m3 (inclusive). to_m3 NULL = no upper limit.
CREATE TABLE tariff_tier (
  tariff_tier_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tariff_schedule_id  BIGINT UNSIGNED NOT NULL,
  tier_no             INT NOT NULL,
  from_m3             INT NOT NULL,
  to_m3               INT NULL,
  rate_per_m3         DECIMAL(10,4) NOT NULL,
  PRIMARY KEY (tariff_tier_id),
  UNIQUE KEY uq_tier_order (tariff_schedule_id, tier_no),
  CONSTRAINT fk_tier_schedule FOREIGN KEY (tariff_schedule_id)
    REFERENCES tariff_schedule (tariff_schedule_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tier_range CHECK (from_m3 >= 1 AND (to_m3 IS NULL OR to_m3 >= from_m3))
) ENGINE=InnoDB;

-- REVISION 5 (Phase 5 Slice 2): v4 plus additive changes: penalty basis 'remaining_unpaid',
-- bill.tariff_snapshot, penalty_charge.bill_id (one penalty per bill), and bill_correction (append-only).
-- Penalty definitions (legacy index_penalty) with an EXPLICIT basis and unit.
-- Legacy penalty_rate has no recorded unit. The live code treats it as a
-- percentage of year-to-date unpaid amount. DECISION D-10 must confirm this.
CREATE TABLE penalty_code (
  penalty_code          VARCHAR(20) NOT NULL,           -- index_penalty.penaltycode
  penalty_after_months  INT NOT NULL DEFAULT 0,         -- penalty_after
  days_applied_after    INT NOT NULL DEFAULT 0,         -- daysappliedafter (no live reader found)
  penalty_info          TEXT NULL,
  created_on            DATE NULL,
  created_by            VARCHAR(20) NULL,
  PRIMARY KEY (penalty_code),
  CONSTRAINT fk_penalty_user FOREIGN KEY (created_by)
    REFERENCES index_systemusers (username) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE penalty_rule (
  penalty_rule_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  penalty_code        VARCHAR(20) NOT NULL,
  basis               ENUM('percent_of_ytd_unpaid','percent_of_bill','fixed_amount','remaining_unpaid') NOT NULL,
  rate                DECIMAL(10,4) NOT NULL,           -- percent (or amount for fixed_amount)
  effective_from      DATE NOT NULL,
  effective_to        DATE NULL,
  unit_status         ENUM('confirmed','unconfirmed') NOT NULL DEFAULT 'unconfirmed',
  source_note         VARCHAR(200) NULL,
  PRIMARY KEY (penalty_rule_id),
  CONSTRAINT fk_penalty_rule_code FOREIGN KEY (penalty_code)
    REFERENCES penalty_code (penalty_code) ON DELETE RESTRICT,
  KEY ix_penalty_rule_code (penalty_code, effective_from)
) ENGINE=InnoDB;

CREATE TABLE discount_code (
  discount_code       VARCHAR(20) NOT NULL,             -- index_discount.discountcode
  discount_percent    INT NOT NULL,                     -- discount_rate
  created_on          DATE NOT NULL,
  created_by          VARCHAR(20) NULL,
  PRIMARY KEY (discount_code),
  CONSTRAINT fk_discount_user FOREIGN KEY (created_by)
    REFERENCES index_systemusers (username) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Billing configuration. Defaults reproduce current behaviour.
-- allocation_policy 'manual_selection' = cashier chooses bills (current live payment screens).
-- 'fifo' is NOT active until approved (business-rule change, D-9).
CREATE TABLE billing_policy (
  billing_policy_id       INT UNSIGNED NOT NULL AUTO_INCREMENT,
  allocation_policy       ENUM('manual_selection','fifo') NOT NULL DEFAULT 'manual_selection',
  rounding_mode           ENUM('legacy_unrounded','half_up_2dp') NOT NULL DEFAULT 'legacy_unrounded', -- DECISION D-16
  effective_from          DATE NOT NULL,
  PRIMARY KEY (billing_policy_id)
) ENGINE=InnoDB;

CREATE TABLE system_setting (
  system_setting_id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  current_year        INT NOT NULL,
  current_month       INT NOT NULL,
  authors             VARCHAR(100) NOT NULL,
  PRIMARY KEY (system_setting_id),
  CONSTRAINT chk_setting_month CHECK (current_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;

-- Legacy index_revenuecode. Kept in full. Not read by any live code path.
CREATE TABLE revenue_setting (
  revenue_setting_id                              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  application_fee                                 DOUBLE NOT NULL DEFAULT 0,
  mayors_permit                                   DOUBLE NOT NULL DEFAULT 0,
  gravel_excavation                               DOUBLE NOT NULL DEFAULT 0,
  asphalted_road                                  DOUBLE NOT NULL DEFAULT 0,
  cemented_road                                   DOUBLE NOT NULL DEFAULT 0,
  additionalfee_pipe_of_20_lineal_feet            DOUBLE NOT NULL DEFAULT 0,
  residentialservice_per_month                    DOUBLE NOT NULL DEFAULT 0,
  commercialservice_per_month                     DOUBLE NOT NULL DEFAULT 0,
  residentialservice_excess_per_cubicmeter        DECIMAL(12,2) NOT NULL DEFAULT 0,
  commercialservice_excess_per_cubicmeter         DECIMAL(12,2) NOT NULL DEFAULT 0,
  drilling_from_mainline                          DOUBLE NOT NULL DEFAULT 0,
  reinstallation_fee                              DOUBLE NOT NULL DEFAULT 0,
  tapping_fee                                     DOUBLE NOT NULL DEFAULT 0,
  repair_fee                                      DOUBLE NOT NULL DEFAULT 0,
  transfer_fee                                    DOUBLE NOT NULL DEFAULT 0,
  three_month_penalty                             DOUBLE NOT NULL DEFAULT 0,
  send_disconnection_notice_after                 INT NOT NULL DEFAULT 0,
  disconnection_after                             INT NOT NULL DEFAULT 0,
  penalty_after                                   INT NOT NULL DEFAULT 0,
  fix_amount_penalty                              DOUBLE NOT NULL DEFAULT 0,
  percentage_penalty                              DECIMAL(10,4) NOT NULL DEFAULT 0,
  PRIMARY KEY (revenue_setting_id)
) ENGINE=InnoDB;

-- =============================================================================
-- 2. CUSTOMERS, METERS, CONNECTIONS
-- =============================================================================

CREATE TABLE customer (
  customer_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  first_name      VARCHAR(50) NOT NULL DEFAULT '',
  middle_name     VARCHAR(50) NOT NULL DEFAULT '',
  last_name       VARCHAR(50) NOT NULL DEFAULT '',
  birth_date      DATE NULL,
  sex             VARCHAR(6) NULL,
  email           VARCHAR(100) NULL,
  mobile_number   VARCHAR(20) NOT NULL DEFAULT '',
  picture_path    VARCHAR(100) NULL,
  PRIMARY KEY (customer_id),
  KEY ix_customer_name (last_name, first_name)
) ENGINE=InnoDB;

-- meter_number is NOT unique here. DECISION D-4 after a duplicate check.
CREATE TABLE meter (
  meter_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  meter_number    VARCHAR(20) NULL,                     -- index_consumerinfo.meternumber
  PRIMARY KEY (meter_id),
  KEY ix_meter_number (meter_number)
) ENGINE=InnoDB;

CREATE TABLE connection (
  consumer_id           VARCHAR(15) NOT NULL,           -- legacy natural key, kept
  customer_id           BIGINT UNSIGNED NOT NULL,
  meter_id              BIGINT UNSIGNED NULL,
  barangay_id           BIGINT UNSIGNED NOT NULL,       -- installation_address_id
  consumer_type_code    VARCHAR(20) NOT NULL,
  penalty_code          VARCHAR(20) NULL,               -- legacy default 'POO1' kept as data (must exist)
  home_address          VARCHAR(50) NOT NULL DEFAULT '',
  sitio                 VARCHAR(100) NULL,
  initial_meter_reading INT NOT NULL,
  status                INT NOT NULL,
  is_stopped            TINYINT(1) NOT NULL DEFAULT 0,  -- stopmeterflag
  is_disconnected       TINYINT(1) NOT NULL DEFAULT 0,  -- disconnectionflag
  is_deleted            TINYINT(1) NOT NULL DEFAULT 0,  -- deleteflag (soft delete)
  is_exempt             TINYINT(1) NOT NULL DEFAULT 0,  -- excep_accnt
  date_added            DATE NULL,
  -- Cached snapshots (legacy behaviour depends on them). Not facts. See D-7.
  cached_current_balance DOUBLE NOT NULL DEFAULT 0,  -- current_bal
  cached_excess          DOUBLE NOT NULL DEFAULT 0,  -- excess
  cached_cumulative      DOUBLE NOT NULL DEFAULT 0,  -- cummulative
  cached_current_reading INT NOT NULL DEFAULT 0,            -- current_reading
  penalty_counter        INT NULL,                          -- penaltycounter (event-driven state, not derivable)
  first_transaction_year INT NULL,                          -- first_tran
  PRIMARY KEY (consumer_id),
  CONSTRAINT fk_connection_customer FOREIGN KEY (customer_id)
    REFERENCES customer (customer_id) ON DELETE RESTRICT,
  CONSTRAINT fk_connection_meter FOREIGN KEY (meter_id)
    REFERENCES meter (meter_id) ON DELETE RESTRICT,
  CONSTRAINT fk_connection_barangay FOREIGN KEY (barangay_id)
    REFERENCES barangay (barangay_id) ON DELETE RESTRICT,
  CONSTRAINT fk_connection_type FOREIGN KEY (consumer_type_code)
    REFERENCES consumer_type (consumer_type_code) ON DELETE RESTRICT,
  CONSTRAINT fk_connection_penalty FOREIGN KEY (penalty_code)
    REFERENCES penalty_code (penalty_code) ON DELETE RESTRICT,
  CONSTRAINT chk_connection_flags CHECK (is_stopped IN (0,1) AND is_disconnected IN (0,1)
                                         AND is_deleted IN (0,1) AND is_exempt IN (0,1)),
  KEY ix_connection_barangay (barangay_id),
  KEY ix_connection_type (consumer_type_code),
  KEY ix_connection_customer (customer_id)
) ENGINE=InnoDB;

-- =============================================================================
-- 3. METER READINGS (separate from bills, per the investigation)
-- =============================================================================

-- Every legacy row that carries a reading becomes one row here.
--   * legacy Billing, is_issue=0           -> kind 'regular'
--   * legacy Billing, is_issue=1           -> kind 'issue_flag'
--   * legacy Reset Meter                   -> kind 'reset'
-- Duplicates are loaded with status 'pending_review'. None are deleted.
CREATE TABLE meter_reading (
  meter_reading_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  consumer_id           VARCHAR(15) NOT NULL,
  billing_year          INT NOT NULL,
  billing_month         TINYINT NOT NULL,
  reading_kind          ENUM('regular','reset','issue_flag') NOT NULL,
  status                ENUM('active','pending_review','superseded') NOT NULL DEFAULT 'active',
  reading_value         INT NULL,                       -- meterReading (NULL is allowed; see exceptions)
  previous_reading      INT NULL,                       -- prevReading (as stored by legacy; not recomputed)
  consumption           INT NULL,                       -- usage (as stored by legacy)
  recorded_by           VARCHAR(50) NULL,               -- processedBy (free text in legacy)
  recorded_on           DATE NULL,                      -- date
  legacy_transaction_id INT NULL,
  -- Generated key: exists only for active rows, so the rule is "one active reading per kind per month".
  active_reading_key    VARCHAR(80) GENERATED ALWAYS AS (
                          IF(status = 'active',
                             CONCAT(consumer_id, '|', billing_year, '|', billing_month, '|', reading_kind),
                             NULL)) STORED,
  PRIMARY KEY (meter_reading_id),
  UNIQUE KEY uq_reading_active (active_reading_key),
  UNIQUE KEY uq_reading_legacy (legacy_transaction_id),
  KEY ix_reading_latest (consumer_id, billing_year, billing_month),
  CONSTRAINT fk_reading_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT chk_reading_month CHECK (billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;
-- DECISION (not in this schema): which reading is the "latest" for billing. The
-- schema stores every candidate. The rule is set after the reconciliation run.

-- =============================================================================
-- 4. MONTHLY BILLS AND PENALTIES
-- =============================================================================

-- Monthly bills only. Fee installments are in fee_charge, not here.
-- Legacy Billing rows with is_issue=1 are NOT bills (they carry no charge);
-- they become meter_reading rows of kind 'issue_flag'.
CREATE TABLE bill (
  bill_id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  consumer_id           VARCHAR(15) NOT NULL,
  billing_year          INT NOT NULL,
  billing_month         TINYINT NOT NULL,
  meter_reading_id      BIGINT UNSIGNED NULL,           -- the regular reading this bill was computed from
  tariff_schedule_id    BIGINT UNSIGNED NULL,           -- which tariff regime applied (backfilled by period, verified)
  consumer_type_code    VARCHAR(20) NULL,               -- legacy transactions.contypeid (as stored)
  bill_amount           DOUBLE NULL,             -- legacy bill (may be NULL in legacy)
  previous_bill_amount  DOUBLE NULL,             -- previousBill
  amount_due            DOUBLE NULL,             -- amount_due
  is_paid               TINYINT(1) NOT NULL DEFAULT 0,  -- is_billpaid (cache; allocations are the fact)
  months_not_paid       INT NOT NULL DEFAULT 0,         -- legacy counter (maintained only by manual jobs)
  is_excess_extracted   TINYINT(1) NOT NULL DEFAULT 0,  -- isExcess_Extracted (no live reader found)
  remarks               TEXT NULL,
  processed_by          VARCHAR(50) NULL,
  billed_on             DATE NULL,
  status                ENUM('active','pending_review','superseded') NOT NULL DEFAULT 'active',
  legacy_transaction_id INT NULL,
  tariff_snapshot       JSON NULL,                      -- applied tariff inputs at issue time (never recomputed)
  -- One active monthly bill per consumer per period.
  active_bill_key       VARCHAR(64) GENERATED ALWAYS AS (
                          IF(status = 'active',
                             CONCAT(consumer_id, '|', billing_year, '|', billing_month),
                             NULL)) STORED,
  PRIMARY KEY (bill_id),
  UNIQUE KEY uq_bill_active (active_bill_key),
  UNIQUE KEY uq_bill_legacy (legacy_transaction_id),
  KEY ix_bill_unpaid (consumer_id, is_paid, billing_year, billing_month),
  CONSTRAINT fk_bill_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT fk_bill_reading FOREIGN KEY (meter_reading_id)
    REFERENCES meter_reading (meter_reading_id) ON DELETE RESTRICT,
  CONSTRAINT fk_bill_tariff FOREIGN KEY (tariff_schedule_id)
    REFERENCES tariff_schedule (tariff_schedule_id) ON DELETE RESTRICT,
  CONSTRAINT fk_bill_consumer_type FOREIGN KEY (consumer_type_code)
    REFERENCES consumer_type (consumer_type_code) ON DELETE RESTRICT,
  CONSTRAINT chk_bill_month CHECK (billing_month BETWEEN 1 AND 12),
  CONSTRAINT chk_bill_paid CHECK (is_paid IN (0,1))
) ENGINE=InnoDB;

-- Penalty charges. Stores the basis and the inputs used, so the amount can be
-- explained later. Legacy rows have NULL inputs and are flagged.
CREATE TABLE penalty_charge (
  penalty_charge_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  consumer_id           VARCHAR(15) NOT NULL,
  billing_year          INT NOT NULL,
  billing_month         TINYINT NOT NULL,
  penalty_rule_id       BIGINT UNSIGNED NULL,           -- NULL for legacy rows (rule cannot be proven)
  basis_used            ENUM('percent_of_ytd_unpaid','percent_of_bill','fixed_amount','legacy_unknown','remaining_unpaid') NOT NULL,
  base_amount           DOUBLE NULL,
  rate_used             DECIMAL(10,4) NULL,
  amount                DOUBLE NOT NULL,
  charge_source         ENUM('system','manual') NOT NULL,
  processed_by          VARCHAR(50) NULL,
  charged_on            DATE NULL,
  legacy_transaction_id INT NULL,
  bill_id               BIGINT UNSIGNED NULL,           -- the overdue bill this penalty was assessed on (one per bill)
  PRIMARY KEY (penalty_charge_id),
  UNIQUE KEY uq_penalty_legacy (legacy_transaction_id),
  UNIQUE KEY uq_penalty_bill (bill_id),
  KEY ix_penalty_period (consumer_id, billing_year, billing_month),
  CONSTRAINT fk_penalty_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT fk_penalty_rule FOREIGN KEY (penalty_rule_id)
    REFERENCES penalty_rule (penalty_rule_id) ON DELETE RESTRICT,
  CONSTRAINT fk_penalty_bill FOREIGN KEY (bill_id)
    REFERENCES bill (bill_id) ON DELETE RESTRICT,
  CONSTRAINT chk_penalty_month CHECK (billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;

-- Reading corrections (Phase 5 Slice 2). APPEND-ONLY: rows are never updated or deleted by the application.
-- Each superseded bill can be corrected once. Payments and allocations are never changed by a correction.
CREATE TABLE bill_correction (
  correction_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  consumer_id           VARCHAR(15) NOT NULL,
  superseded_bill_id    BIGINT UNSIGNED NOT NULL,
  corrected_bill_id     BIGINT UNSIGNED NOT NULL,
  billing_year          INT NOT NULL,
  billing_month         TINYINT NOT NULL,
  old_reading           INT NULL,
  new_reading           INT NOT NULL,
  old_amount            DOUBLE NULL,
  new_amount            DOUBLE NULL,
  difference            DOUBLE NOT NULL,
  reason                VARCHAR(500) NOT NULL,
  performed_by          VARCHAR(20) NOT NULL,
  performed_on          DATETIME(6) NOT NULL,
  PRIMARY KEY (correction_id),
  UNIQUE KEY uq_correction_superseded (superseded_bill_id),
  KEY ix_correction_period (consumer_id, billing_year, billing_month),
  CONSTRAINT fk_correction_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT fk_correction_superseded FOREIGN KEY (superseded_bill_id)
    REFERENCES bill (bill_id) ON DELETE RESTRICT,
  CONSTRAINT fk_correction_corrected FOREIGN KEY (corrected_bill_id)
    REFERENCES bill (bill_id) ON DELETE RESTRICT,
  CONSTRAINT chk_correction_month CHECK (billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;

-- =============================================================================
-- 5. ADDITIONAL FEES
-- =============================================================================

CREATE TABLE fee_plan (
  fee_plan_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  consumer_id           VARCHAR(15) NOT NULL,
  fee_name              VARCHAR(100) NOT NULL,
  amount                DOUBLE NOT NULL,
  months                INT NOT NULL,
  month_counter         INT NOT NULL DEFAULT 0,         -- recorded installments (kept; see F-1)
  remainder             DOUBLE NOT NULL DEFAULT 0, -- legacy remainder (INT in legacy)
  start_month           TINYINT NULL,                   -- legacy month (usage not confirmed)
  start_year            INT NULL,                       -- legacy year
  processed_by          VARCHAR(50) NULL,
  date_added            DATE NOT NULL,
  legacy_fee_id         INT NULL,
  PRIMARY KEY (fee_plan_id),
  UNIQUE KEY uq_fee_plan_legacy (legacy_fee_id),
  CONSTRAINT fk_fee_plan_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT chk_fee_counter CHECK (month_counter >= 0)
) ENGINE=InnoDB;

-- One fee charge per plan per period per kind. Several plans for one consumer
-- in the same month are allowed, because the uniqueness is per plan.
CREATE TABLE fee_charge (
  fee_charge_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  fee_plan_id           BIGINT UNSIGNED NOT NULL,
  billing_year          INT NOT NULL,
  billing_month         TINYINT NOT NULL,
  charge_kind           ENUM('installment','remainder') NOT NULL,
  amount                DOUBLE NOT NULL,
  status                ENUM('active','pending_review','superseded') NOT NULL DEFAULT 'active',
  charged_on            DATE NULL,
  processed_by          VARCHAR(50) NULL,               -- 'System' for generated charges
  legacy_transaction_id INT NULL,
  active_fee_key        VARCHAR(120) GENERATED ALWAYS AS (
                          IF(status = 'active',
                             CONCAT(fee_plan_id, '|', billing_year, '|', billing_month, '|', charge_kind),
                             NULL)) STORED,
  PRIMARY KEY (fee_charge_id),
  UNIQUE KEY uq_fee_charge_active (active_fee_key),
  UNIQUE KEY uq_fee_charge_legacy (legacy_transaction_id),
  CONSTRAINT fk_fee_charge_plan FOREIGN KEY (fee_plan_id)
    REFERENCES fee_plan (fee_plan_id) ON DELETE RESTRICT,
  CONSTRAINT chk_fee_charge_month CHECK (billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;

-- Legacy AdditionalFeesPayment. Not linked to a fee_charge: the legacy data
-- does not record which charge a payment settled, and it is not inferred.
CREATE TABLE fee_payment (
  fee_payment_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  fee_plan_id           BIGINT UNSIGNED NOT NULL,
  amount                DOUBLE NOT NULL,
  processed_by          VARCHAR(50) NULL,
  remarks               VARCHAR(100) NOT NULL DEFAULT '',
  paid_on               DATE NOT NULL,
  legacy_afpayment_id   INT NULL,
  legacy_addfeepay_id   VARCHAR(100) NOT NULL,          -- unique in legacy
  PRIMARY KEY (fee_payment_id),
  UNIQUE KEY uq_fee_payment_legacy (legacy_afpayment_id),
  UNIQUE KEY uq_fee_payment_code (legacy_addfeepay_id),
  CONSTRAINT fk_fee_payment_plan FOREIGN KEY (fee_plan_id)
    REFERENCES fee_plan (fee_plan_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- =============================================================================
-- 6. RECEIPTS, DISCOUNTS, ALLOCATIONS
-- =============================================================================

-- Legacy 'Received Amount' rows. One receipt row per legacy row.
CREATE TABLE receipt (
  receipt_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  consumer_id           VARCHAR(15) NOT NULL,
  or_number             VARCHAR(100) NOT NULL,          -- NOT unique in legacy; several bills share one OR
  amount_received       DOUBLE NOT NULL,         -- receivedamt
  billing_year          INT NULL,                       -- legacy year the receipt was entered against
  billing_month         TINYINT NULL,
  received_on           DATE NULL,
  processed_by          VARCHAR(50) NULL,
  remarks               TEXT NULL,
  legacy_transaction_id INT NULL,
  link_status           ENUM('allocated','unallocated','ambiguous') NOT NULL DEFAULT 'unallocated',
  PRIMARY KEY (receipt_id),
  UNIQUE KEY uq_receipt_legacy (legacy_transaction_id),
  KEY ix_receipt_or (or_number),
  KEY ix_receipt_consumer (consumer_id, received_on),
  CONSTRAINT fk_receipt_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT chk_receipt_month CHECK (billing_month IS NULL OR billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;

-- Legacy 'Discount' rows. A discount is attached to a receipt only when the
-- legacy link (receipt.discountcode holding the discount row's id) resolves.
CREATE TABLE discount_application (
  discount_application_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  receipt_id              BIGINT UNSIGNED NULL,         -- NULL when the legacy link cannot be proven
  consumer_id             VARCHAR(15) NOT NULL,
  discount_code           VARCHAR(20) NOT NULL,
  discount_amount         DOUBLE NOT NULL,       -- legacy payment on the Discount row (may be 0; see F-2)
  billing_year            INT NULL,
  billing_month           TINYINT NULL,
  processed_by            VARCHAR(50) NULL,
  applied_on              DATE NULL,
  legacy_transaction_id   INT NULL,
  PRIMARY KEY (discount_application_id),
  UNIQUE KEY uq_discount_legacy (legacy_transaction_id),
  CONSTRAINT fk_discount_receipt FOREIGN KEY (receipt_id)
    REFERENCES receipt (receipt_id) ON DELETE RESTRICT,
  CONSTRAINT fk_discount_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT fk_discount_code FOREIGN KEY (discount_code)
    REFERENCES discount_code (discount_code) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- Legacy 'Payment' rows. Each row says how much of a receipt was applied to
-- which bill. A row is linked only when the rule in MIGRATION_MAPPING_v2 is
-- certain. Otherwise bill_id and/or receipt_id stay NULL and link_status says why.
CREATE TABLE payment_allocation (
  payment_allocation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  consumer_id           VARCHAR(15) NOT NULL,           -- always known from the legacy row
  billing_year          INT NOT NULL,
  billing_month         TINYINT NOT NULL,
  receipt_id            BIGINT UNSIGNED NULL,
  bill_id               BIGINT UNSIGNED NULL,
  amount_applied        DOUBLE NOT NULL,         -- legacy payment, as stored
  applied_on            DATE NULL,
  processed_by          VARCHAR(50) NULL,
  link_status           ENUM('linked','linked_amount_differs','unlinked_no_bill',
                             'ambiguous_bill','ambiguous_receipt') NOT NULL,
  legacy_transaction_id INT NULL,
  PRIMARY KEY (payment_allocation_id),
  UNIQUE KEY uq_alloc_legacy (legacy_transaction_id),
  KEY ix_alloc_bill (bill_id),
  KEY ix_alloc_receipt (receipt_id),
  KEY ix_alloc_period (consumer_id, billing_year, billing_month),
  CONSTRAINT fk_alloc_receipt FOREIGN KEY (receipt_id)
    REFERENCES receipt (receipt_id) ON DELETE RESTRICT,
  CONSTRAINT fk_alloc_bill FOREIGN KEY (bill_id)
    REFERENCES bill (bill_id) ON DELETE RESTRICT,
  CONSTRAINT fk_alloc_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT chk_alloc_month CHECK (billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;
-- Note: legacy amounts are not constrained to be positive. Legacy partial logic
-- can produce a negative value, and it is kept as stored (see F-5).

-- Legacy excess_log. Target must be a receipt. If it is not, receipt_id stays NULL.
CREATE TABLE excess_credit (
  excess_credit_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  receipt_id            BIGINT UNSIGNED NULL,
  consumer_id           VARCHAR(15) NOT NULL,
  billing_year          INT NOT NULL,
  billing_month         TINYINT NOT NULL,
  excess_amount         DOUBLE NULL,             -- excessamt (nullable in legacy)
  recorded_on           DATE NOT NULL,
  is_used               TINYINT(1) NOT NULL DEFAULT 0,
  legacy_excess_log_id  INT NULL,
  legacy_transaction_id INT NULL,
  PRIMARY KEY (excess_credit_id),
  UNIQUE KEY uq_excess_legacy (legacy_excess_log_id),
  CONSTRAINT fk_excess_receipt FOREIGN KEY (receipt_id)
    REFERENCES receipt (receipt_id) ON DELETE RESTRICT,
  CONSTRAINT fk_excess_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT chk_excess_month CHECK (billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;

-- Legacy partial_log. The sign is kept as stored (negative for underpayment).
CREATE TABLE partial_payment_log (
  partial_payment_log_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  receipt_id              BIGINT UNSIGNED NULL,
  consumer_id             VARCHAR(15) NOT NULL,
  billing_year            INT NOT NULL,
  billing_month           TINYINT NOT NULL,
  partial_amount          DOUBLE NULL,           -- partialamt, sign as stored
  paid_on                 DATE NOT NULL,
  legacy_partial_log_id   INT NULL,
  legacy_transaction_id   INT NULL,
  PRIMARY KEY (partial_payment_log_id),
  UNIQUE KEY uq_partial_legacy (legacy_partial_log_id),
  CONSTRAINT fk_partial_receipt FOREIGN KEY (receipt_id)
    REFERENCES receipt (receipt_id) ON DELETE RESTRICT,
  CONSTRAINT fk_partial_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT chk_partial_month CHECK (billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;

CREATE TABLE unpaid_snapshot (
  unpaid_snapshot_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  consumer_id           VARCHAR(15) NOT NULL,
  billing_year          INT NOT NULL,
  billing_month         TINYINT NOT NULL,
  unpaid_amount         DOUBLE NOT NULL,
  date_unpaid           DATE NOT NULL,
  legacy_unpaid_id      BIGINT NULL,
  PRIMARY KEY (unpaid_snapshot_id),
  UNIQUE KEY uq_unpaid_legacy (legacy_unpaid_id),
  CONSTRAINT fk_unpaid_connection FOREIGN KEY (consumer_id)
    REFERENCES connection (consumer_id) ON DELETE RESTRICT,
  CONSTRAINT chk_unpaid_month CHECK (billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;

-- =============================================================================
-- 7. ISSUES AND MESSAGES
-- =============================================================================

-- Verified targets (code review): every issue points at a legacy Billing row.
--   * add_issue()                      -> target is an is_issue=1 row  -> meter_reading_id
--   * set_overdue_months() (manual)    -> target is an unpaid is_issue=0 row -> bill_id
-- Exactly one target is set.
CREATE TABLE issue (
  issue_id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  meter_reading_id      BIGINT UNSIGNED NULL,
  bill_id               BIGINT UNSIGNED NULL,
  issue_text            VARCHAR(100) NOT NULL,
  issue_date            DATE NOT NULL,
  last_comment          VARCHAR(100) NULL,
  issued_by             VARCHAR(100) NULL,              -- free text in legacy ('System' or a username)
  is_seen               TINYINT(1) NOT NULL DEFAULT 0,
  status                VARCHAR(20) NOT NULL DEFAULT 'Pending',
  legacy_issue_id       INT NULL,
  PRIMARY KEY (issue_id),
  UNIQUE KEY uq_issue_legacy (legacy_issue_id),
  CONSTRAINT fk_issue_reading FOREIGN KEY (meter_reading_id)
    REFERENCES meter_reading (meter_reading_id) ON DELETE RESTRICT,
  CONSTRAINT fk_issue_bill FOREIGN KEY (bill_id)
    REFERENCES bill (bill_id) ON DELETE RESTRICT,
  CONSTRAINT chk_issue_one_target CHECK ((meter_reading_id IS NULL) <> (bill_id IS NULL))
) ENGINE=InnoDB;

CREATE TABLE issue_message (
  issue_message_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  issue_id              BIGINT UNSIGNED NOT NULL,
  from_username         VARCHAR(20) NOT NULL,
  to_username           VARCHAR(20) NOT NULL,
  message_text          VARCHAR(100) NOT NULL,
  sent_on               DATE NOT NULL,
  sent_at               TIME(6) NOT NULL,
  is_read               TINYINT(1) NOT NULL DEFAULT 0,
  legacy_message_id     INT NULL,
  PRIMARY KEY (issue_message_id),
  UNIQUE KEY uq_msg_legacy (legacy_message_id),
  CONSTRAINT fk_msg_issue FOREIGN KEY (issue_id)
    REFERENCES issue (issue_id) ON DELETE RESTRICT,
  CONSTRAINT fk_msg_from FOREIGN KEY (from_username)
    REFERENCES index_systemusers (username) ON DELETE RESTRICT,
  CONSTRAINT fk_msg_to FOREIGN KEY (to_username)
    REFERENCES index_systemusers (username) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- =============================================================================
-- 8. REPORTING SUMMARY (replaces the 36 monthly columns of index_barangayrecord)
-- =============================================================================

CREATE TABLE barangay_monthly_summary (
  summary_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  barangay_id           BIGINT UNSIGNED NOT NULL,
  billing_year          INT NOT NULL,
  billing_month         TINYINT NOT NULL,
  total_due             DOUBLE NOT NULL DEFAULT 0,
  total_paid            DOUBLE NOT NULL DEFAULT 0,
  total_usage           INT NOT NULL DEFAULT 0,
  PRIMARY KEY (summary_id),
  UNIQUE KEY uq_summary_period (barangay_id, billing_year, billing_month),
  CONSTRAINT fk_summary_barangay FOREIGN KEY (barangay_id)
    REFERENCES barangay (barangay_id) ON DELETE RESTRICT,
  CONSTRAINT chk_summary_month CHECK (billing_month BETWEEN 1 AND 12)
) ENGINE=InnoDB;

-- =============================================================================
-- 9. MIGRATION TRACEABILITY AND SAFETY (new database only)
-- =============================================================================

-- One row per legacy index_transactions row. Maps to its target row, or to an exception.
CREATE TABLE legacy_transaction_map (
  legacy_transaction_id INT NOT NULL,
  legacy_trans_type     VARCHAR(20) NOT NULL,           -- transType as found
  legacy_is_issue       TINYINT(1) NOT NULL,
  target_table          VARCHAR(40) NULL,               -- NULL when held only in an exception
  target_id             BIGINT UNSIGNED NULL,
  mapping_rule          VARCHAR(20) NOT NULL,           -- rule id, e.g. 'MR-03'
  migrated_at           DATETIME(6) NOT NULL,
  PRIMARY KEY (legacy_transaction_id)
) ENGINE=InnoDB;

-- Anything that could not be placed with certainty. Holds the raw legacy row as JSON.
CREATE TABLE migration_exception (
  migration_exception_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  exception_code        VARCHAR(40) NOT NULL,           -- catalogue in MIGRATION_MAPPING_v2 section 6
  source_table          VARCHAR(64) NOT NULL,
  source_key            VARCHAR(100) NOT NULL,
  candidate_keys        JSON NULL,                      -- ids that could not be chosen between
  detail                TEXT NULL,
  raw_row_json          JSON NULL,
  resolution_status     ENUM('open','approved','resolved') NOT NULL DEFAULT 'open',
  resolution_note       TEXT NULL,
  PRIMARY KEY (migration_exception_id),
  KEY ix_exception_code (exception_code, resolution_status)
) ENGINE=InnoDB;

-- Copies of rows that the application deletes, written before the delete.
-- Keeps the user-visible delete behaviour and makes it recoverable.
CREATE TABLE removed_record_audit (
  removed_record_audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_table          VARCHAR(64) NOT NULL,
  source_key            VARCHAR(100) NOT NULL,
  row_json              JSON NOT NULL,
  removed_by            VARCHAR(20) NULL,
  removed_on            DATETIME(6) NOT NULL,
  reason                VARCHAR(200) NULL,
  PRIMARY KEY (removed_record_audit_id),
  KEY ix_removed_source (source_table, source_key)
) ENGINE=InnoDB;

-- =============================================================================
-- END OF DRAFT v2. Not executed. See PROPOSED_NORMALIZED_SCHEMA_v2.md section 9.
-- =============================================================================
