# Phase 5 – Complete Cumulative Overlay (Slices 1 to 4, checkpoint)

**Apply to:** your ORIGINAL Phase 4 project (`waterbillV4-janice_43d942.zip`, Phase 4 state, migrations 0001 and 0002 already present).
**Package:** `Phase_5_Cumulative_Overlay.zip` – 33 files, one ZIP, to be applied once.
**Project folder:** `C:\Users\chuan\Downloads\JANICEEEE\waterbillV4`

> **Status: checkpoint, not the finished Phase 5.** This package contains everything from Slices 1, 2, 3 and the
> consumer-lifecycle part of Slice 4. Still guarded (shows a message, changes nothing) and **not yet migrated**: the
> dashboard, consumer issues, reports, bulk meter reading, fee management and fee payment screens, penalty management,
> discount management, and the correction screens for payments and readings (command line for readings only).
> Do **not** treat normalized mode as production-ready. No test, audit, or migration was run by me.

## 1. Before you copy

- The 11 files marked **REPLACES** overwrite your Phase 4 versions completely. If you have edited any of them locally,
  stop and tell me which ones; they must be merged, not replaced.
- Do not paste `.env` anywhere.

## 2. Copy the package (PowerShell)

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Cumulative_Overlay.zip"   # change if saved elsewhere
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::OpenRead($Z).Entries.Count      # expected: 33
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
cd C:\Users\chuan\Downloads\JANICEEEE\waterbillV4
Test-Path "wb_core\migrations\0003_slice2_billing.py", "wb_core\services\payments.py", "wb_core\services\lifecycle.py"
```

**Expected:** `33`, then three `True` lines.

## 3. Environment settings (`.env`, add or change only these keys)

```text
WB_BUSINESS_DB=legacy
```

- `legacy` (default): every screen behaves as before. **Keep this for production.**
- `normalized`: the migrated screens use `waterbilling_v4`. Testing only, until the checkpoint limits in section 6 are closed.

Keys that already exist in your `.env` (database names and credentials) are not changed by this package.
Required names: `WB_DEFAULT_DB_NAME` (the legacy test copy, not `waterbillingv3`), `WB_NORMALIZED_DB_NAME=waterbilling_v4`.

## 4. Migration order and database preparation

Your Phase 4 project already has migrations `0001` and `0002` applied to `waterbilling_v4`. This package adds **one**
migration, `0003`. It is additive only (two enum values, one column, one unique foreign key, one table).

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py showmigrations wb_core --database normalized     # expected: 0001, 0002 marked [X]; 0003 [ ]
python manage.py migrate wb_core --database normalized           # applies 0003 only
python manage.py showmigrations wb_core --database normalized     # expected: 0003 now [X]
python manage.py wb_verify_schema                                 # expected: Schema verification PASSED
```

**Reference data (needed before consumers can be created in normalized mode).** This copies barangays, consumer types,
penalty codes and discount codes from the approved test copy. It writes no customers, bills or payments. Run the plan
first, then write once you approve:

```powershell
python manage.py wb_init_reference
python manage.py wb_init_reference --execute
```

**Penalty rule (needed before penalties can be assessed).** Create a rule with basis `remaining_unpaid` and unit
status `confirmed` for each penalty code in use. Rules imported from legacy are not used. Until this exists, a reading
for a consumer past the penalty threshold is refused with a message and nothing is saved.

## 5. Tests you will run later

```powershell
python -m unittest discover -s wb_core\tests -p "test_static_*.py" -t .
python manage.py check
python manage.py test index.test_business_consumers
python manage.py test index.test_business_readings
python manage.py test index.test_mark_unpaid
python manage.py test wb_core.tests.test_django_database
python manage.py test wb_core.tests.test_django_phase2
python manage.py test wb_core.tests.test_django_dryrun
python manage.py test wb_core.tests.test_django_importer
```

Expected: the static suite and the checks pass. The Django suites use temporary test databases only.
`test_django_importer` and `test_django_dryrun` came from earlier phases. `test_business_readings` was retargeted in
this package to the dashboard route, which is still guarded.

## 6. Startup

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
```

Log in with the existing account. In `legacy` mode the application behaves as before. In `normalized` mode the consumer
list, create and edit, readings, ledger, payment, receipts, and the lifecycle actions use `waterbilling_v4`. The
dashboard is guarded (the login redirect goes to the consumer list).

## 7. Manual verification checklist (normalized mode, test data only)

| Route or action | Expected |
|---|---|
| Consumer list, search | Lists only normalized consumers; search works |
| Create a consumer | New consumer in `waterbilling_v4`; no legacy row created |
| Edit a consumer | Same account updated; a failed edit does not create a second consumer |
| Reading entry (a month) | Reading and bill created; second entry for the month refused |
| Penalty after a missed month | One penalty per overdue bill (needs a confirmed rule) |
| Correction (command line) | Old bill superseded, correction row written, payments unchanged |
| Ledger | Billing rows with Paid / NotFullyPaid / Unpaid; fee rows; balance |
| Payment with a new OR number | One receipt; allocations per bill; bills already paid skipped |
| Payment with a used OR number | Refused; nothing saved |
| Discount code on a payment | Discount on bills only; unknown code refused |
| Stop / enable meter, new meter | Flag toggles; reset reading and new meter recorded |
| Exempt account | Flag toggles; barangay monthly totals adjusted |
| Disconnect / reconnect | Flag set to on / off |
| Delete consumer | Hidden from the list; audit copy in `removed_record_audit` |
| Undo delete | Consumer visible again |
| Dashboard, reports, issues, bulk reading, fee screens | Message shown; nothing changed |
| Any legacy consumer row | Unchanged by normalized-mode actions |

## 8. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `Schema verification` shows `DIFF` | Migration 0003 not applied, or applied to the wrong database | Run section 4 again; send the output |
| `OR number ... already used` | OR number reused | Use a new OR number; this is intended |
| `Penalty code ... no confirmed rule` on a reading | Penalty rule missing or unconfirmed | Create the rule (section 4) |
| `Reference data missing` on create | `wb_init_reference --execute` not run | Run it after approval |
| `NoReverseMatch` in tests | Route parameter names differ | Check `index\urls.py` and tell me the names |
| Login lands on the consumer list | Dashboard guarded in normalized mode | Expected; switch back to `legacy` for the dashboard |
| Any error with "Nothing was changed" | Known problem handled safely | Read the message; it is not a fault in the data |

## 9. Rollback

- **Files:** restore the 11 REPLACED files from the original Phase 4 ZIP, and delete the 22 NEW files. Then
  `python manage.py check`.
- **Database:** migration `0003` has no automatic reverse, and it is additive. The Phase 4 code ignores its additions.
  Any rows written to `bill_correction`, penalty charges linked to bills, receipts, allocations and fee payments stay.
  Removing them, or dropping columns or the table, is a database operation that needs your approval first.
- **Setting:** set `WB_BUSINESS_DB=legacy` to stop normalized behaviour without touching files.

## 10. Known limitations and deferred decisions

1. **Checkpoint, not complete.** Remaining Slice 4 work is listed in section 10 and in `README_PHASE5_SLICE4.md`.
2. **Route inventory is not complete.** Only the routes changed in Slices 1 to 4 have been checked. Before any real use of
   normalized mode, every route that reads business data must be listed and either migrated or guarded.
3. **Partial payments and excess credits** are not created from the payment screen. The allocation order and the handling
   of leftover money are undecided.
4. **Payment editing and reversal** have no screen. The legacy edit screen is guarded. A reversal policy is undecided.
5. **Discounts apply to bills only.** Extending them to additional fees needs an approved rule.
6. **Penalties** are assessed only on reading save, and only with a confirmed `remaining_unpaid` rule. No schedule was added.
7. **Corrections** of readings use the administrator command line. Later bills are flagged for review, not rebuilt.
   Penalties stay on superseded bills; they are not moved.
8. **Discount and penalty management screens** are not built.

## 11. File inventory (33 files)

| # | File (copy to this path under your project folder) | New or replaces |
|---|---|---|
| 1 | `index\business_db.py` | NEW |
| 2 | `index\business_forms.py` | NEW |
| 3 | `index\business_lifecycle.py` | NEW |
| 4 | `index\business_payments.py` | NEW |
| 5 | `index\business_readings.py` | NEW |
| 6 | `index\business_views.py` | NEW |
| 7 | `index\test_business_consumers.py` | NEW |
| 8 | `index\test_business_readings.py` | NEW |
| 9 | `index\views.py` | REPLACES |
| 10 | `wb2\settings.py` | REPLACES |
| 11 | `wb_core\management\commands\wb_correct_reading.py` | NEW |
| 12 | `wb_core\management\commands\wb_init_reference.py` | NEW |
| 13 | `wb_core\management\commands\wb_verify_schema.py` | REPLACES |
| 14 | `wb_core\mapping.py` | REPLACES |
| 15 | `wb_core\migrations\0003_slice2_billing.py` | NEW |
| 16 | `wb_core\models\__init__.py` | REPLACES |
| 17 | `wb_core\models\corrections.py` | NEW |
| 18 | `wb_core\models\readings_bills.py` | REPLACES |
| 19 | `wb_core\models\reference.py` | REPLACES |
| 20 | `wb_core\monetary.py` | REPLACES |
| 21 | `wb_core\services\billing.py` | NEW |
| 22 | `wb_core\services\billing_rules.py` | NEW |
| 23 | `wb_core\services\consumer_rules.py` | NEW |
| 24 | `wb_core\services\consumers.py` | NEW |
| 25 | `wb_core\services\ledger_view.py` | NEW |
| 26 | `wb_core\services\lifecycle.py` | NEW |
| 27 | `wb_core\services\payments.py` | NEW |
| 28 | `wb_core\sql\normalized_schema_v5.sql` | NEW |
| 29 | `wb_core\tests\test_static_migrations.py` | REPLACES |
| 30 | `wb_core\tests\test_static_models.py` | REPLACES |
| 31 | `wb_core\tests\test_static_slice1.py` | NEW |
| 32 | `wb_core\tests\test_static_slice2.py` | NEW |
| 33 | `wb_core\tools\generate_migration.py` | REPLACES |

**Summary:** 22 NEW files, 11 REPLACED files. The NEW files do not exist in the Phase 4 project. The REPLACED files
overwrite the Phase 4 versions.
