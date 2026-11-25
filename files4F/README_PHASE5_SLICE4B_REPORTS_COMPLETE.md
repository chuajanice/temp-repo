# Phase 5 – Slice 4B (part 5): All Report Routes on the Normalized Database

**Overlay:** `Phase_5_Slice4B_Reports_Complete_Overlay.zip` (4 files)
**Apply on top of:** the Slice 4B Part 4 state (Reports Part 3 and Part 4 applied).

> **Read this first.** This part completes **every report route** named in the Slice 4 list. Nothing in this overlay
> was tested by me. Other Slice 4 work (bulk reading, fees, penalties, discounts, payment correction, reading deletion)
> and Slice 5 are **not** in this overlay yet.

## 1. Report routes: status of all of them

| # | Route | Status |
|---|---|---|
| 1 | Barangay report (opened from the Reports menu) | Done (Reports Part 3) |
| 2 | Monthly collections | Done (Reports Part 3) |
| 3 | Barangay detail | Done (Reports Part 4) |
| 4 | Usage report data | Done (Reports Part 4) |
| 5 | Revenue report | **Done in this part** |
| 6 | Consumption report | **Done in this part** |
| 7 | Record list | **Done in this part** |
| 8 | Monthly consumer summary | **Done in this part** |
| 9 | Monthly billing report (with Excel export) | **Done in this part** |
| 10 | Average consumption report (with Excel export) | **Done in this part** |
| – | Unsettled bills drill-down (linked from the consumption page) | **Still guarded** (see section 4) |

## 2. Files

| File | New or replaces | Purpose |
|---|---|---|
| `wb_core\services\reports.py` | REPLACES | Figures for the revenue, consumption, record list, consumer summary, billing matrix and average consumption reports |
| `index\business_reports.py` | REPLACES | Handlers for all report routes in this part |
| `index\views.py` | REPLACES | Revenue, consumption, record list and consumer summary branches; unsettled-bills guard |
| `index\reports.py` | REPLACES | Billing report and average consumption branches (Excel export kept) |

## 3. Decisions and assumptions in this part (read these)

These are the points where the normalized data does not match the legacy data exactly. Each one is documented in
the code and must be confirmed by you.

1. **"Paid" bills.** Legacy used a paid flag on each bill. The normalized flag is not updated after creation, so a bill
   counts as paid when its remaining amount (bill amount minus allocations and discounts for its period) is zero.
2. **Fee receivable and collected (revenue report).** Legacy used a link between fee plans and transactions that does
   not carry over. Normalized rule used: **expected** = the full value (instalment × months) of fee plans that start in the
   year; **collected** = fee payments made in the year. This is an **assumption to confirm**.
3. **Usage.** Usage is taken from active regular bills. Legacy also summed issue rows; those are review requests, not bills.
4. **Consumption report, consumers with no bill this year.** Legacy counts them in the "<=5" usage range. This is kept,
   as legacy behaviour. Note it if you want it changed.
5. **Consumption report, deleted-consumer balances.** Calculated as all active bills and penalties, minus all allocations
   and discounts, over all years. Superseded bills are excluded.
6. **Consumption report, years of first transaction.** Uses the stored first-transaction year when present, otherwise the
   earliest active bill year.
7. **Monthly consumer summary.** Keeps the legacy formula: the month's bill, plus the consumer's current balance, plus that
   month's fee instalment. Keeps the legacy behaviour of adding the current balance to every month. The "amount paid"
   is the allocations for the month, so part payments show (legacy showed zero for unpaid bills).
   The penalty column was never set by the legacy view, so it stays blank.
8. **Unpaid total on the consumer summary** uses the remaining-amount rule from the dashboard.
9. **Average consumption report** keeps the **hard-coded consumer type `C002`** from the legacy code. Change it only with
   your approval.
10. **Record list.** Barangays are selected by their legacy barangay id, which the existing select posts. A consumer
    appears when they have a receipt in the chosen month; the first one is shown, as before. Deleted consumers are included,
    as before.
11. **Excel exports** (billing report and average consumption) reuse the existing export code without change.

## 4. Still guarded (not part of the report list)

- **Unsettled bills drill-down** (`view_unsettled_bills`), linked from the consumption page's deleted-consumer table. It
  is a consumer-level drill-down. It shows a message and changes nothing until it is migrated (planned with the payment work).

## 5. Permissions

- Barangay report, barangay detail, usage report, revenue report: tellers and supervisors only, as before.
- Consumption report, record list, consumer summary, billing report, average consumption: no role check, as before.

## 6. Apply

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Slice4B_Reports_Complete_Overlay.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::OpenRead($Z).Entries | ForEach-Object { $_.FullName } | Sort-Object   # expected: 4 lines
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
```

## 7. Rollback

Restore the four files from the Slice 4B Part 4 state. No database change is involved.
