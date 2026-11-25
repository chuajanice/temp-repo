# Phase 5 – Slice 4B (part 1): Dashboard and Meter-Reading List on the Normalized Database

**Overlay:** `Phase_5_Slice4B_Part1_Overlay.zip` (4 files)
**Apply on top of:** the Slice 4A state (Slices 1 to 3 and Slice 4A applied).

> **Read this first.** This part completes the **dashboard** (the page after login) and the **meter-reading list**
> that readers land on. It does **not** complete Slice 4B. Still to do: consumer issues, reports, bulk meter reading,
> fee management and fee payment screens, penalty management, discount management, and the payment edit and reading
> delete routes. Those routes still show a message and change nothing. The final cumulative overlay will follow when
> all of Slice 4B is done.
> No test was run by me, and no migration is included.

## 1. Files

| File | New or replaces | Purpose |
|---|---|---|
| `wb_core\services\dashboard.py` | NEW | Unpaid-amount helper (remaining amount of unpaid bills) and summary years |
| `index\business_dashboard.py` | NEW | Dashboard (bills list) and meter-reading list handlers |
| `index\views.py` | REPLACES | Dashboard guard replaced by a branch; meter-reading list branch added |
| `index\test_business_readings.py` | REPLACES | Routing test now uses a route that is still guarded (additional-fee payment) |

## 2. What the dashboard does in normalized mode

- Same role rules as before: teller and supervisor see the list; administrators go to user management; readers go to
  the meter-reading list.
- Same search (meter number, consumer number, or name and address) and the same ordering and pagination.
- Each row shows the consumer and the amount they owe on unpaid bills. **That amount is the remaining unpaid amount of
  each unpaid bill, not the full bill amount.** This is the one intended change in the figure: a part-paid bill is no
  longer counted at full value.
- The legacy dashboard has **no statistics**. The normalized dashboard shows none either, because adding statistics would
  change the page. If statistics are wanted, that needs a template change, which is outside this scope.

## 3. What the meter-reading list does in normalized mode

- Lists consumers who are not deleted and not disconnected, with the same search, ordering and pagination.
- Month and year choices come from the normalized barangay summaries, plus the current year, newest first.
- Readers and tellers and supervisors see it. Others are sent to the dashboard, as before.

## 4. Apply

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Slice4B_Part1_Overlay.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::OpenRead($Z).Entries | ForEach-Object { $_.FullName } | Sort-Object   # expected: 4 lines
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
```

## 5. Rollback

Restore `index\views.py` and `index\test_business_readings.py` from the Slice 4A state, and delete
`wb_core\services\dashboard.py` and `index\business_dashboard.py`. No database change is involved.

## 6. Still to do in Slice 4B (not in this part)

1. Consumer issues: create, list, view, status and messages.
2. Reports: billing, payment and collection, outstanding balance, consumer and meter, and other reporting functions.
3. Bulk meter reading, with validation, bill creation and duplicate-period protection.
4. Fee management: plans, additional charges, instalments and payments.
5. Penalty management: rules and assessment history. Unconfirmed rules stay disabled.
6. Discount management: creation, editing and history. Discounts stay on bills only.
7. Payment edit and reading delete, through an auditable correction path. Records are never silently overwritten or deleted.
