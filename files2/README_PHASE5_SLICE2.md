# Phase 5 – Slice 2: Meter Readings, Bills, Penalties and Reading Corrections (normalized database)

**Project folder on your PC:** `C:\Users\chuan\Downloads\JANICEEEE\waterbillV4`
**Overlay file:** `Phase_5_Slice2_Overlay.zip` (19 files, each stored at its project path)
**Apply on top of:** the Slice 1 result (Slice 1 overlay applied to your uploaded project).

> **Read this first.**
> - Slice 2 covers the **single reading screen**, bill creation, **penalties**, the **penalty counter**, and
>   **administrator reading corrections**.
> - **Not in Slice 2 (still legacy, or guarded):** the bulk reading screen, deleting a reading, stop/enable/exempt,
>   issues, consumer disconnect/reconnect/delete, the ledger, the bills list, payments, receipts, additional fees,
>   and the dashboard. Those are Slices 3 and 4. Until then, **normalized mode is for testing only.**
> - **Nothing was executed by me.** I ran the static tests (294 passed on a copy of the Slice 1 result with this
>   overlay applied) and the generators. I did **not** run any Django command, Django test, migration or database
>   operation. The behavioural tests in `index/test_business_readings.py` are written but not run.
> - Migration `0003` is **additive only** (two enum values, one new column, one new unique foreign key, one new
>   table). Nothing is dropped, renamed or converted. It is the one change that touches `waterbilling_v4`.

---

## 1. Files in this overlay

| File | New or replaces | Purpose |
|---|---|---|
| `wb_core\sql\normalized_schema_v5.sql` | NEW | v4 plus the additive Slice 2 changes (reference for the verification command) |
| `wb_core\migrations\0003_slice2_billing.py` | NEW | Applies the additive changes to `waterbilling_v4` |
| `wb_core\models\corrections.py` | NEW | `BillCorrection` model (append-only) |
| `wb_core\models\readings_bills.py` | REPLACES | `Bill.tariff_snapshot`; `PenaltyCharge.bill` (one penalty per bill); new penalty basis value |
| `wb_core\models\reference.py` | REPLACES | `PenaltyRule.basis` accepts `remaining_unpaid` |
| `wb_core\models\__init__.py` | REPLACES | Exports `BillCorrection` |
| `wb_core\services\billing_rules.py` | NEW | Pure rules: penalty base, overdue run, counter, threshold, tariff regime |
| `wb_core\services\billing.py` | NEW | Readings, bills, penalties and corrections, each in one transaction on `normalized` |
| `index\business_readings.py` | NEW | Normalized reading screen and the "not yet available" response for unmigrated routes |
| `wb_core\management\commands\wb_correct_reading.py` | NEW | Administrator correction command (plan by default) |
| `index\views.py` | REPLACES | One branch on the reading screen and one guard on each unmigrated route. **No legacy line removed.** |
| `wb_core\tools\generate_migration.py` | REPLACES | Keeps migration `0001` exactly as applied (excludes the Slice 2 additions) |
| `wb_core\monetary.py` | REPLACES | Money policy includes the three new `bill_correction` money columns (DOUBLE) |
| `wb_core\mapping.py` | REPLACES | Registers `BillCorrection` |
| `wb_core\management\commands\wb_verify_schema.py` | REPLACES | Checks against `normalized_schema_v5.sql` |
| `wb_core\tests\test_static_models.py` | REPLACES | Compares models with v5; expects 32 models |
| `wb_core\tests\test_static_slice1.py` | REPLACES | Slice 1 guard count relaxed to "at least four" (Slice 2 adds more) |
| `wb_core\tests\test_static_slice2.py` | NEW | Pure rule tests and safety/structure tests (run by me: all pass) |
| `index\test_business_readings.py` | NEW | Django behavioural tests for Slice 2 (**not run by me**) |

**Frontend:** no template, CSS or JavaScript file is changed. The reading screen renders `input-meter-reading.html`
with the same context names as before.

---

## 2. The rules as implemented (read this before testing)

### 2.1 Overdue bill
An **overdue bill** is an active regular bill whose **remaining unpaid amount** is at least half a centavo, and whose
billing period is **earlier than the consumer's latest billed period**. The latest bill is never overdue, because its
period has not closed yet.

### 2.2 Remaining unpaid amount (the penalty base)
For each bill:

    remaining = bill amount − (sum of all payment allocations for that account and billing period)

- Allocations are summed exactly (`math.fsum`), including allocations linked to a superseded bill of the same period.
- Payments reduce the remaining amount. A zero or negative remaining amount is never penalised.
- "Paid" means remaining is below half a centavo. That threshold only absorbs binary floating-point residue.

### 2.3 Penalty counter (derived, never saved as a running total)
The counter is **the number of consecutive unpaid monthly periods, counted backwards from the most recent overdue
period**. It is recalculated from the bills and allocations every time a reading is saved. It is stored only as a
cache on the connection, for display.

- It is **not** incremented by saving a reading. (The legacy code's increment was lost; see section 7.)
- It **resets to zero** when the most recent overdue period is fully paid, or when there is no overdue period.
- A **missing monthly bill breaks the run**: a month with no bill does not count.

### 2.4 Threshold and penalty
- The threshold is the **`penalty_after` setting** of the consumer's penalty code (`penalty_after_months`).
- A penalty is assessed when **counter ≥ threshold**.
- The penalty applies to **every overdue unpaid bill in the current run** that does not yet have a penalty.

**Formula:**

    penalty = rate × remaining unpaid ÷ 100

- `rate` comes from the penalty rule in effect on the assessment date. The rule must have basis
  `remaining_unpaid` and unit status `confirmed`. The rate is copied to the penalty record (`rate_used`).
- If the remaining amount is zero or negative, or the rate is zero, **no penalty is created**.

### 2.5 Worked example (rate 2%, threshold 1 month)

| Step | What happens |
|---|---|
| January 2026 reading saved | Bill for January = 80.00. Not paid. No penalty (only one bill exists). |
| February 2026 reading saved | February bill created. January is now overdue: remaining 80.00, run = [January], counter = 1 ≥ 1. |
| Penalty assessed | 2% × 80.00 ÷ 100 = **1.60**, one penalty record linked to the January bill. |
| Saving the February reading again is impossible | A period can hold only one reading. Re-running the assessment creates **no** second penalty (one penalty per bill). |
| Customer pays January in full, then a March reading is saved | Remaining January = 0 → run is empty → counter resets to 0. No new penalty. |
| Overpayment of 50 on January | Remaining = −50 → no penalty. |

### 2.6 When penalties are assessed (the timing)
Penalties are assessed **only when a reading is saved** for that consumer. This is the same trigger the legacy code
used. Nothing runs on a schedule, and corrections never assess penalties.

- **Consequence:** a consumer who receives no new reading is never assessed, even if bills are overdue.
- **Consequence:** if the penalty rule is missing, the reading is **refused** and nothing is saved (see section 4).

### 2.7 Exempt accounts
An exempt account gets a **zero bill** for every reading and is **never penalised**. Its counter is kept at zero.

### 2.8 Tariff snapshot
Each bill stores the tariff inputs it was computed with (`tariff_snapshot`: minimum block, minimum charge, rate after
the minimum, tariff regime, previous reading, reading, usage). A later tariff change **never** recalculates an issued
bill. The regime boundaries are the same as the legacy `bill_compute`.

### 2.9 Processor
Every record stores the **authenticated username as text** (`processed_by`, `recorded_by`, `performed_by`). There is
no cross-database foreign key.

### 2.10 Errors and transactions
Each reading save and each correction is **one transaction** on `waterbilling_v4`.
- Known problems (duplicate period, missing rule, missing tariff, invalid input) are shown as messages. Nothing is saved.
- Unexpected errors are **not** caught by the business code. The transaction rolls back, the error is logged, and a
  message says that no changes were made. No bill is ever created because an error happened.
- A reading form that submits several months saves them **all or none**.

---

## 3. Reading corrections (append-only)

### 3.1 Who and why
- Only an **active administrator** (`is_admin = 1` in the legacy user table) may correct a reading.
- A **reason is mandatory** (1 to 500 characters).
- The frontend has **no correction screen** (frontend unchanged). The correction is made with the command in section 5.

### 3.2 What a correction does (one transaction)
1. The **old reading** is marked `superseded`. Its value is kept.
2. A **new reading** is created as the active reading for the period.
3. The **old bill** is marked `superseded`. Its amount and tariff snapshot are kept.
4. A **new bill** is created with the corrected amount. It uses the **original tariff terms** from the old bill's snapshot.
5. A **`bill_correction` row** is written: old reading, new reading, old amount, new amount, difference, reason,
   administrator username, time. Rows are never updated or deleted by the application.
6. The consumer's cached balance is refreshed.

### 3.3 Payment allocations during a correction (reconciliation)
**Allocations are never changed, moved, deleted or re-pointed.** Payment history is therefore preserved exactly.

The balance of a billing period is recomputed from the **active bill** and **all allocations of that period**:

    remaining (corrected bill) = new amount − (all allocations of the period)

**Worked example.** January bill was 80.00. Customer paid 50.00 (allocation kept). The reading is corrected and the
new bill is 100.00.

| | Before correction | After correction |
|---|---|---|
| Active January bill | 80.00 (bill A) | 100.00 (bill B) |
| Superseded January bill | — | 80.00 (bill A, status superseded, kept) |
| January allocations | 50.00 | 50.00 (unchanged) |
| January remaining | 30.00 | **50.00** |
| Correction row | — | old 80.00, new 100.00, difference +20.00 |

If the corrected amount is **lower** than the payments already made, the remaining amount is negative, which is shown
as an overpayment. It is never penalised.

### 3.4 Rules that keep a correction safe
- A bill can be **corrected only once** (unique key on the superseded bill). A second correction must be a new
  correction of the corrected bill, which is a later decision.
- A correction **never assesses a penalty**. An existing penalty stays on its superseded bill.
- A correction **does not change any later bill**. If later bills exist, the command says so. Their usage and amounts
  are **not** recalculated automatically (see section 7).

---

## 4. Penalty rule setup (needed before penalties can run)

The penalty service refuses to run without a rule that matches **all** of these:
- `penalty_code` = the consumer's penalty code (usually `P001`),
- `basis` = `remaining_unpaid`,
- `unit_status` = `confirmed`,
- `effective_from` on or before today, and `effective_to` empty or after today.

Rules imported from legacy have basis `percent_of_ytd_unpaid` and status `unconfirmed`. They are **not** used.
Until an administrator creates a matching rule, a reading for a consumer whose penalty threshold is reached is
**refused** with a message, and nothing is saved. This is deliberate. Creating the rule is an administrator task
(see section 7).

---

## 5. Apply the overlay

### Step 5.1 – Check the zip contents (nothing is changed yet)

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Slice2_Overlay.zip"   # change if you saved it elsewhere
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::OpenRead($Z).Entries | ForEach-Object { $_.FullName } | Sort-Object
```

**Expected:** 19 lines, starting with `index/business_readings.py`.

### Step 5.2 – Extract into the project folder

```powershell
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
```

**Expected:** no output and no error.

### Step 5.3 – Check the new files are in place

```powershell
cd C:\Users\chuan\Downloads\JANICEEEE\waterbillV4
Test-Path "wb_core\migrations\0003_slice2_billing.py", "wb_core\services\billing.py", "wb_core\models\corrections.py"
```

**Expected:** three lines, all `True`.

---

## 6. Run the local checks

```powershell
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s wb_core\tests -p "test_static_*.py" -t .
python wb_core\tools\generate_migration.py --check
python wb_core\tools\generate_money_migration.py --check
python manage.py check
```

**Expected:**
- `Ran 294 tests` and `OK`.
- `OK: migration is up to date` (twice).
- `System check identified no issues (0 silenced).`

If the static tests fail, stop and send me the output.

---

## 7. Apply migration 0003 and verify the schema (approval point)

Migration `0003` changes `waterbilling_v4`. It is additive only. **Run it only when you are ready.**

```powershell
python manage.py migrate wb_core --database normalized
python manage.py wb_verify_schema
```

**Expected:** the migration reports `Applying wb_core.0003_slice2_billing... OK`. Then
`Schema verification PASSED`. Any `DIFF:` line means the database and the reviewed schema differ. Stop and send me the output.

---

## 8. Run the Django tests for Slice 2 (temporary test databases)

```powershell
python manage.py test index.test_business_readings
```

**Expected:** `OK`, with 19 tests run. These have **not** been run by me. If any test fails, send me the full output.

**Check first if a test fails with `NoReverseMatch` on `inputreading`:** the two routing tests use the parameter names
`id` and `year`. Check `index\urls.py` for the `inputreading` path and tell me the names if they differ.

---

## 9. Use the normalized reading screen (testing only)

1. In `.env`, set `WB_BUSINESS_DB=normalized` (Slice 1 section 4). Start the server with `python manage.py runserver`.
2. Open a consumer created in Slice 1, then open its reading screen. Save a reading for a month.
3. The reading is saved, a bill appears, and the screen reloads.
4. Try saving a second reading for the same month: the message says a correction is needed, and nothing changes.
5. Stop the server and set `WB_BUSINESS_DB=legacy` again.

---

## 10. Correct a reading (administrator, command line)

Plan first. This changes nothing:

```powershell
python manage.py wb_correct_reading --connection 0000000002-01 --year 2026 --month 3 --reading 1250 --reason "Meter misread at source" --admin-username <your-admin-username>
```

**Expected:** `Current: reading ..., bill amount ...` and `PLAN ONLY`.

Apply the correction:

```powershell
python manage.py wb_correct_reading --connection 0000000002-01 --year 2026 --month 3 --reading 1250 --reason "Meter misread at source" --admin-username <your-admin-username> --execute
```

**Expected:** `Corrected. Old amount ..., new amount ....` If later bills exist, a `NOTE` line says they were not changed.

The command refuses if the user is not an active administrator, if the reason is blank, or if there is no active bill for
the period.

---

## 11. Verification checklist for Slice 2

| Check | How | Expected |
|---|---|---|
| Static suite | section 6 | 294 OK |
| Schema matches v5 | `wb_verify_schema` (after 0003) | PASSED |
| Reading creates bill and snapshot | section 9 | Bill appears; snapshot present in the database |
| Duplicate reading refused | section 9 step 4 | Message; no second row |
| Penalty once per bill | Django test `test_penalty_is_not_duplicated...` | 1 penalty |
| Counter derived | Django test `test_counter_is_derived...` | counter 1 after repeated assessment |
| Correction append-only | Django test `test_correction_supersedes...` | old bill superseded, correction row present |
| Allocations unchanged | Django test `test_payments_are_untouched...` | allocation amount unchanged |
| Routing guards | Django test `test_unmigrated_route_is_refused...` | redirect; legacy consumer rows unchanged |

---

## 12. Rollback

**Files.** Slice 2 changes 10 existing files and adds 9 new ones. Restore the 10 from the Slice 1 result, and delete
the 9 new ones. The Slice 1 result is your uploaded project plus the Slice 1 overlay.

**Database.** Migration `0003` has no automatic reverse. The old code ignores the new column, the new penalty
link and the new table, so the old code still runs. Any correction rows already written stay in `bill_correction`, and
the application never deletes them. Removing them, or dropping the columns or table, is a database operation that
needs your approval first.

---

## 13. Known limits and open decisions

1. **Penalty rule maintenance has no screen.** An administrator creates the `remaining_unpaid` confirmed rule in the
   database (or asks for a screen). Decision needed: who maintains rules, and how?
2. **Penalties are assessed only on reading save.** A consumer with no new reading is never assessed. Decision needed:
   whether a monthly penalty run should be added. That would be a new trigger, so I did not add one.
3. **Corrections have no screen.** The administrator uses the command. Decision needed: whether a screen is wanted,
   which would be a new frontend page.
4. **A correction does not recalculate later bills.** Their usage and amounts stay as they were. Decision needed:
   whether a correction should also rebuild following periods, and how that would be recorded.
5. **A penalty stays on the superseded bill** after a correction and is not re-based. Decision needed: whether the
   penalty should be re-based on the corrected bill.
6. **Previous reading.** A new reading uses the latest earlier reading for that account, not the latest reading
   overall. This only differs when readings are entered out of order. Legacy used the latest overall.
7. **Negative usage** (a reading lower than the previous one) is accepted, as in legacy, and charged the minimum.
8. **Legacy penalty rows** (imported history) are not counted by the normalized assessment.
9. **Legacy penalty counter finding.** From the code (not from a run): the legacy counter increment is overwritten by a
   later save in both the single-reading and bulk paths, so it is effectively never persisted. Confirm on
   `waterbilling_v4_test` before relying on any legacy figure. The normalized counter is derived, so this does not
   affect Slice 2.
10. **Not in Slice 2:** bulk reading, delete reading, stop/enable/exempt, issues, consumer lifecycle, ledger, bills
    list, payments, receipts, additional fees, dashboard. Routes to these are guarded or still legacy, as listed in section 1.
