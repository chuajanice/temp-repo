# Phase 5 – Slice 1: Customers, Connections and Meters on the Normalized Database

**Project folder on your PC:** `C:\Users\chuan\Downloads\JANICEEEE\waterbillV4`
**Overlay file:** `Phase_5_Slice1_Overlay.zip` (11 files, each stored at its project path)
**Based on:** your uploaded project ZIP (`waterbillV4-janice_43d942.zip`).

> **Read this first – what Slice 1 is and is not.**
> - **Slice 1 covers only:** the consumer list (with search), creating a consumer (customer + meter + connection),
>   and editing a consumer. These screens can run on the normalized database.
> - **Not in Slice 1 yet:** meter readings, billing, the ledger, payments and receipts, fees, penalties, discounts,
>   issues, reports and the dashboard. They still use the legacy tables. Phase 5 is **not complete**. The later slices
>   are still to be built.
> - **Mixing is possible.** With `WB_BUSINESS_DB=normalized`, the consumer screens use `waterbilling_v4`, but the other
>   screens still read the legacy tables. Use `normalized` only to test Slice 1. Do not run live billing on it yet.
> - **Nothing was executed by me.** The static checks were run (268 tests, all passing on a copy of your project with
>   this overlay applied). **No Django command, Django test or database operation was run by me.** Section 6 lists
>   what you must run.

---

## 1. What the overlay changes

| File | New or replaces | Purpose |
|---|---|---|
| `index\business_db.py` | NEW | Reads the `WB_BUSINESS_DB` setting (`legacy` default, or `normalized`) |
| `index\business_forms.py` | NEW | The consumer form on the normalized database (same fields and widgets as the legacy form) |
| `index\business_views.py` | NEW | Normalized versions of the consumer list, create and edit screens. Same templates, same context names |
| `wb_core\services\consumers.py` | NEW | Service for customers, connections and meters, in one transaction each, on the `normalized` alias |
| `wb_core\services\consumer_rules.py` | NEW | Pure rules: the consumer-number rule and the default penalty code |
| `wb_core\management\commands\wb_init_reference.py` | NEW | Copies reference records (barangays, consumer types, penalty and discount codes) into `waterbilling_v4` |
| `index\test_business_consumers.py` | NEW | Django behaviour tests for Slice 1 (not run by me) |
| `wb_core\tests\test_static_slice1.py` | NEW | Static tests for Slice 1 (run by me: all pass) |
| `wb2\settings.py` | REPLACES | Adds the `WB_BUSINESS_DB` setting, checked at start-up |
| `index\views.py` | REPLACES | Adds 4 guarded branches (one per screen, plus the landing page). **17 lines added, none removed** |
| `wb_core\tests\test_static_migrations.py` | REPLACES | The stale migration-hash table is corrected to the real files (same fix as Phases 3 and 4) |

**Frontend:** no template, CSS or JavaScript file is changed. The normalized screens render the existing templates.
**Database schema:** no migration and no SQL change in Slice 1. The Phase 4 schema is used as it is.
**Monetary fields:** unchanged (DOUBLE). Slice 1 has no money fields.

---

## 2. Before you copy the files

Make sure your project is at the Phase 4 state you uploaded, and that the `.env` file exists in the project folder.
Do not paste `.env` anywhere.

---

## 3. Copy the overlay into your project

### Step 3.1 – Check the zip contents (nothing is changed yet)

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Slice1_Overlay.zip"   # change if you saved it elsewhere
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::OpenRead($Z).Entries | ForEach-Object { $_.FullName } | Sort-Object
```

**Expected:** 11 lines, starting with `index/business_db.py` and including `wb_core/tests/test_static_slice1.py`.

### Step 3.2 – Extract into the project folder

```powershell
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
```

**Expected:** no output and no error. Only these 11 files are written.

### Step 3.3 – Check the new files are in place

```powershell
cd C:\Users\chuan\Downloads\JANICEEEE\waterbillV4
Test-Path "index\business_views.py", "wb_core\services\consumers.py", "wb_core\management\commands\wb_init_reference.py"
```

**Expected:** three lines, all `True`.

---

## 4. Configuration (no secrets)

Open `.env` in Notepad, **only to add or change this line** (do not paste the file anywhere):

```text
WB_BUSINESS_DB=legacy
```

- `legacy` (the default): nothing changes. Every screen works as before. **Keep this value until you have tested Slice 1.**
- `normalized`: the consumer screens use `waterbilling_v4`. Use this only for testing (see section 6).

Any other value stops the application at start-up with a clear message.

---

## 5. Run the local checks

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

**Expected:** the prompt starts with `(.venv)`.

### Step 5.1 – Static tests (no database needed)

```powershell
python -m unittest discover -s wb_core\tests -p "test_static_*.py" -t .
```

**Expected:** `Ran 268 tests` and then `OK`.

### Step 5.2 – Django system check

```powershell
python manage.py check
```

**Expected:** `System check identified no issues (0 silenced).`

---

## 6. Test the consumer screens on the normalized database

### Step 6.1 – Confirm the normalized schema is in place (read-only)

```powershell
python manage.py wb_verify_schema
```

**Expected:** `Schema verification PASSED`. If you see `DIFF:` lines, stop and send me the output.

### Step 6.2 – Plan the reference-data copy (writes nothing)

Slice 1 needs barangays, consumer types and penalty codes in `waterbilling_v4` before a consumer can be created.
This command copies only those reference tables, read-only from the approved test copy. It does **not** copy customers,
bills or payments.

```powershell
python manage.py wb_init_reference
```

**Expected:** the source row counts for barangays, consumer types, penalties and discounts, then `PLAN ONLY`.

### Step 6.3 – Write the reference rows (ONLY after you approve this step)

This writes reference rows to `waterbilling_v4`. It is safe to run again: rows that already exist are reused, not duplicated.

```powershell
python manage.py wb_init_reference --execute
```

**Expected:** `Reference rows created: {...}` and `Rows already present (reused): {...}`.
**Run it a second time:** the created counts must be zero.

### Step 6.4 – Run the Django tests for Slice 1 (uses temporary test databases)

```powershell
python manage.py test index.test_business_consumers
```

**Expected:** `OK`. The test count is 11 (10 tests in normalized mode, 1 in legacy mode).
These tests have **not** been run by me. If any test fails, send me the full output.

### Step 6.5 – Manual test in the browser (optional, on `normalized` only)

1. Set `WB_BUSINESS_DB=normalized` in `.env`, then start the server:

   ```powershell
   python manage.py runserver
   ```

2. Log in as a teller or supervisor (the same account you use today).
3. Open the consumer list. It should be empty, apart from consumers you create now.
4. Click the button to add a consumer. Fill in the form and save.
5. The new consumer should appear in the list, and searching by its last name should find it.
6. Edit the consumer, change the first name and save. The change should appear in the list.
7. Stop the server with `Ctrl + C`, and set `WB_BUSINESS_DB=legacy` again.

**Expected:** every step works, and the page looks exactly as before.

---

## 7. Behaviour changes you should know about

| Change | Why |
|---|---|
| A failed **edit** keeps the edit mode. The retry updates the same account. | The legacy create page dropped the edit flag, so a retry created a **second** customer. |
| The first consumer number on an empty database is `0000000001-01`. | The legacy code crashes on an empty table. |
| The landing page skips its legacy maintenance (excess reset, name rewrites, month-end jobs) in `normalized` mode. | Those writes would change the legacy database. Month-end processing for normalized data is a later slice. |
| The "last account" shown on the create page is read from the normalized database. | Same behaviour, different source. |
| The creation date of a changed connection is set to today on edit. | The legacy edit does this too. It is kept on purpose. |

---

## 8. Known limitations

1. **No user audit on the new records.** The normalized connection table has no column for the user who created or
   changed a record. Slice 1 writes the user name to the application log only. Adding an audit column is a schema
   change, so it needs your approval.
2. **Authentication stays on the legacy database.** Logins are unchanged.
3. **Only the list, create and edit screens are switched.** Stop, enable, disconnect, reconnect and delete (soft
   delete) of consumers are not yet switched in this slice. In `normalized` mode, those buttons still act on the
   legacy tables.
4. **Historical records are not in `waterbilling_v4`.** New consumers appear only when you create them.
5. **Reference rows are copied from the test copy of the legacy data.** Barangays, consumer types and penalty codes
   must match what you use in production. Check them after running `wb_init_reference`.
6. **The default penalty code `P001` must exist.** Without it, creating a consumer shows an error that names the
   missing code and tells you to run `wb_init_reference`.

---

## 9. Rollback

Slice 1 changes three existing files and adds eight new ones. Restore the three existing files from your uploaded ZIP
(`waterbillV4-janice_43d942.zip`), and delete the eight new files.

```powershell
$Orig = "C:\Users\chuan\Downloads\waterbillV4-janice_43d942.zip"   # change to where your original ZIP is
$Tmp  = "$env:TEMP\wb_slice1_original"
Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive -LiteralPath $Orig -DestinationPath $Tmp -Force
$Root = "$Tmp\waterbillV4-janice"
$P    = "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4"

foreach ($f in @("index\views.py", "wb2\settings.py", "wb_core\tests\test_static_migrations.py")) {
    Copy-Item -LiteralPath "$Root\$f" -Destination "$P\$f" -Force
}
foreach ($f in @("index\business_db.py", "index\business_forms.py", "index\business_views.py",
                 "index\test_business_consumers.py", "wb_core\services\consumers.py",
                 "wb_core\services\consumer_rules.py", "wb_core\management\commands\wb_init_reference.py",
                 "wb_core\tests\test_static_slice1.py")) {
    Remove-Item -LiteralPath "$P\$f" -Force -ErrorAction SilentlyContinue
}
```

Then remove the `WB_BUSINESS_DB` line from `.env`, and run `python manage.py check`.

**Important:** rolling back the files does not delete rows that `wb_init_reference --execute` already wrote into
`waterbilling_v4`. Deleting those rows would be a database operation, so it needs your approval first.

---

## 10. Next steps (not part of this overlay)

Slices 2 to 4, as agreed: meter readings and billing; payments, receipts and balances; fees, penalties, discounts,
issues, reports and the dashboard. Each will come as its own overlay and README. Phase 5 is complete only after all
four are tested, and the legacy business screens are no longer used in `normalized` mode.
