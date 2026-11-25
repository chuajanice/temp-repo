# Phase 5 – Slice 4B (part 3): Reports on the Normalized Database

**Overlay:** `Phase_5_Slice4B_Reports_Overlay.zip` (4 files)
**Apply on top of:** the Slice 4B Part 2 state (Slices 1 to 4A, Slice 4B Part 1 and Slice 4B Part 2 applied).

> **Read this first.** This part completes the **barangay report** (the report page that the Reports menu opens) and
> the **monthly collections report**. Other report routes are **guarded**: they show a message and change nothing. They
> are still to do (section 5). Slice 4B is **not** complete. No test was run by me, and no migration is included.

## 1. Files

| File | New or replaces | Purpose |
|---|---|---|
| `wb_core\services\reports.py` | NEW | Live report figures: barangay totals and collection rate; monthly collections and years |
| `index\business_reports.py` | NEW | Barangay report and monthly collections handlers (same templates and context names) |
| `index\views.py` | REPLACES | Two report branches; six report routes guarded |
| `index\reports.py` | REPLACES | Two report routes guarded |

## 2. How the figures are computed

- **Barangay report, per barangay for the selected year:**
  - *Due* = sum of the amounts of active regular bills of the year (exempt accounts have zero bills).
  - *Usage* = sum of the consumption of those bills' readings.
  - *Paid* = sum of payment allocations of the year.
  - *Receivables* = due − paid.
  - *Collection rate* = paid ÷ due × 100, capped at 100 and rounded to 2 places (0 when nothing is due).
  - Totals and the total collection rate are computed the same way.
- **Monthly collections:** receipts grouped by the month they were received. Each month shows the total received and
  the number of receipts. Years come from the receipts, plus the current year.
- Sums use exact addition (`math.fsum`) on the stored values.
- **Why not the barangay summary table:** billing does not keep that table up to date for new records, so figures are
  computed from the bills, allocations and receipts instead.

## 3. Deliberate differences from legacy

| Legacy | Normalized | Why |
|---|---|---|
| Usage summed every billing row, including issue rows | Usage is summed for active regular bills only | Issue rows are review requests, not bills |
| Paid summed receipts by the year of the bill | Paid sums allocations by the bill's year | Same meaning, from the normalized allocations |
| Barangays identified by name | Barangays identified by their record, and shown by name | Same display |

## 4. Access

- The barangay report is for tellers and supervisors only, as before. Others are sent to the dashboard.
- The monthly collections report has no role check, as before.

## 5. Still guarded (not yet migrated, Slice 4B continues)

- Barangay detail (drill-down from the barangay report)
- Revenue report
- Consumption report and usage report data
- Record list
- Monthly consumer summary (per consumer, per year)
- Monthly billing report
- Average consumption report (all consumers)

## 6. Apply

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Slice4B_Reports_Overlay.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::OpenRead($Z).Entries | ForEach-Object { $_.FullName } | Sort-Object   # expected: 4 lines
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
```

## 7. Rollback

Restore `index\views.py` and `index\reports.py` from the Slice 4B Part 2 state, and delete `wb_core\services\reports.py`
and `index\business_reports.py`. No database change is involved.
