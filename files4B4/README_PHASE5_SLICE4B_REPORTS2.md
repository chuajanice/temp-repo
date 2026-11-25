# Phase 5 – Slice 4B (part 4): Barangay Detail and Usage Report on the Normalized Database

**Overlay:** `Phase_5_Slice4B_Reports2_Overlay.zip` (3 files)
**Apply on top of:** the Slice 4B Part 3 state.

> **Read this first.** This part completes **two more report routes**: the barangay detail page (opened from the
> barangay report) and the usage report data. **Six report routes are still guarded** (section 4). They are not
> finished, so they show a message and change nothing. No test was run by me, and no migration is included.

## 1. Files

| File | New or replaces | Purpose |
|---|---|---|
| `wb_core\services\reports.py` | REPLACES | Adds the barangay monthly detail and the barangay-by-month usage matrix |
| `index\business_reports.py` | REPLACES | Adds the two handlers (barangay detail; usage report) |
| `index\views.py` | REPLACES | Two guards replaced by branches to the handlers |

## 2. What the two pages show

- **Barangay detail** (for one barangay and year): one row per month with usage, amount due and amount paid, from
  active regular bills and allocations. Teller and supervisor only. An unknown barangay name shows "not found".
- **Usage report data** (for one year): usage for each barangay by month, monthly totals of usage and of amounts due
  across all barangays, and a total usage per barangay. Teller and supervisor only, as before. Years come from the
  bills, and the current year is used if there are none.

The templates and context names are the same as before.

## 3. Note on the usage matrix

The legacy template reads some attributes that the legacy view did not set. Those render blank both before and now.
This is unchanged on purpose.

## 4. Still guarded (not yet migrated)

- Revenue report (`revenue_report`)
- Consumption report (`consumption`)
- Record list (`record_list`)
- Monthly consumer summary (`monthly_summary`)
- Monthly billing report (`monthly_billing_report` in `reports.py`)
- Average consumption report (`average_consumption_all_report` in `reports.py`)

These six are the remaining report routes. The earlier summary said six guarded routes; the full count is eight. Two of
the eight are done in this part.

## 5. Apply

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Slice4B_Reports2_Overlay.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::OpenRead($Z).Entries | ForEach-Object { $_.FullName } | Sort-Object   # expected: 3 lines
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
```

## 6. Rollback

Restore the three files from the Slice 4B Part 3 state. No database change is involved.
