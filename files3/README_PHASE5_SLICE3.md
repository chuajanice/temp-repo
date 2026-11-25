# Phase 5 – Slice 3: Ledger, Payments, Receipts and Balances (normalized database)

**Project folder on your PC:** `C:\Users\chuan\Downloads\JANICEEEE\waterbillV4`
**Overlay file:** `Phase_5_Slice3_Overlay.zip` (4 files, each stored at its project path)
**Apply on top of:** the Slice 2 result (Slice 1 + Slice 2 overlays applied to your uploaded project).

> **Read this first.**
> - Slice 3 covers the **ledger page** (payment history and outstanding balance), **payment processing**, **receipts**,
>   **payment allocations**, **discounts applied to bills**, and **additional-fee instalment payments**.
> - **Not in Slice 3 (guarded, not migrated):** the dashboard (bills list), the alternate ledger, editing a payment,
>   the monthly payment screen, the additional fees list, and the additional fee payment screens. These show a
>   message in normalized mode and change nothing. They are **Slice 4**.
> - **Not in Slice 3, and not yet decided:** partial payments and excess credits created from this screen. See section 5.
> - **Testing is yours.** As you asked, I did not run any test, audit or verification. This README lists what to run.
> - Slice 3 has **no database migration**. It uses the Slice 2 schema.
> - **Slice 4 and the cumulative Phase 5 overlay are not included in this response.** See section 8.

---

## 1. Files in this overlay

| File | New or replaces | Purpose |
|---|---|---|
| `wb_core\services\payments.py` | NEW | Processes one payment submission in one transaction on `normalized` |
| `wb_core\services\ledger_view.py` | NEW | Builds the ledger rows and balances from the normalized tables (read only) |
| `index\business_payments.py` | NEW | Ledger and payment screen handlers, same templates and context names as before |
| `index\views.py` | REPLACES | Two branches (ledger, payment) and seven guards on unmigrated routes. **No legacy line removed.** |

**Frontend:** no template, CSS or JavaScript file is changed. The ledger renders `ledger.html`; the payment POST
keeps the same form fields (`selected_trans`, `or_num`, `dis_code`).

---

## 2. Payment processing (what happens when a teller submits)

One submission is **one transaction** on `waterbilling_v4`:

1. **OR number** is required (1 to 20 characters) and must not be used by any earlier receipt. A repeat is refused.
2. The **consumer** is locked.
3. A **discount code**, if given, must exist. An unknown code is refused (legacy silently ignored it).
4. Each **selected bill** is locked and checked:
   - it must be an active bill of this consumer;
   - its **remaining unpaid amount** is what gets paid. A bill that is already settled is **skipped** and reported,
     so a double submission cannot pay it twice.
5. Each **selected fee instalment** is locked. If its instalments are already complete it is skipped.
6. **Discount** (bills only): discount = rate × remaining ÷ 100. Cash part = remaining − discount.
7. **One receipt** is created for the total cash, with the OR number.
8. **One payment allocation per bill**, linked to the receipt and the bill, for the cash part.
9. **One discount record per discounted bill**, for the period of that bill.
10. **One fee payment per instalment**, and the plan's instalment counter moves forward by one.
11. The consumer's cached balance is refreshed.

If anything fails, **everything rolls back**. No receipt, allocation or discount is saved.

---

## 3. The ledger page (payment history and balance)

The ledger lists, in period order:
- **Billing rows** from the active bills. Status is **Paid** (nothing remains), **NotFullyPaid** (something was
  settled), or **Unpaid**. Each row shows the reading, previous reading, usage, bill amount, settled amount, the receipt
  reference, and any penalty for that bill.
- **Reset-meter rows.**
- **Additional-fee instalment rows**, generated from each plan's start date. Paid if the instalment counter has passed them.

**Outstanding balance** shown on the page is the consumer's cached balance, refreshed after every payment and every reading.
The "bill balance" is the sum of the remaining unpaid amounts of unpaid bills.

---

## 4. Corrections and history rules

- **A payment is never edited.** The legacy edit-payment screen is **guarded** in normalized mode. Changing a payment
  is a correction that needs a design (see section 5). It is not implemented here.
- **Allocations, receipts and discounts are never changed or deleted** by the application.
- A bill's remaining amount is always: bill amount − allocations − discounts for its period. A later reading correction
  (Slice 2) therefore changes the remaining amount, and the existing payments stay exactly as they were.

---

## 5. Decisions this slice does NOT make (documented, not guessed)

1. **Partial payments and excess credits.** The payment screen has no amount entry: it pays whole remaining amounts of
   the bills you select. A partial amount needs an allocation order (which bill first, and whether to pay the oldest
   first), and a rule for money left over (excess credit or nothing). Those are business decisions. **Decision needed.**
   Existing partial and excess records from history remain visible in the database, but this screen creates none.
2. **Editing or reversing a payment.** Needs an append-only correction design, like the reading correction. **Decision needed.**
3. **Discounts on fees.** Discounts apply to bills only. Whether a discount should also apply to additional fees is
   not decided. **Decision needed.**
4. **Receipt printing.** This slice stores receipts. It does not add a printable receipt screen, because the frontend
   stays unchanged.

---

## 6. Corrections to legacy behaviour (deliberate)

| Legacy behaviour | Normalized behaviour | Why |
|---|---|---|
| Paid the full bill amount even when part was already paid | Pays the **remaining** amount only | Prevents over-payment of a partly paid bill |
| Recorded a payment with no duplicate check | Refuses an OR number that is already used | Prevents duplicate payment processing |
| Discount computed on a zero total (defect U-7), so always zero | Discount = rate × remaining of each selected bill | Restores the intended discount |
| Unknown discount code ignored silently | Refused with a message | No silent fallback |
| No transaction around the payment (defect U-4) | One transaction per submission | Atomicity |
| Blank OR number allowed | OR number required | Needed for the duplicate check |

---

## 7. Apply the overlay

### Step 7.1 – Check the zip contents (nothing is changed yet)

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Slice3_Overlay.zip"   # change if you saved it elsewhere
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::OpenRead($Z).Entries | ForEach-Object { $_.FullName } | Sort-Object
```

**Expected:** 4 lines: `index/business_payments.py`, `index/views.py`, `wb_core/services/ledger_view.py`,
`wb_core/services/payments.py`.

### Step 7.2 – Extract into the project folder

```powershell
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
```

### Step 7.3 – Start the server (testing only, normalized mode)

Set `WB_BUSINESS_DB=normalized` in `.env` (see the Slice 1 README), then:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
```

---

## 8. What is still to do (Slice 4 and the cumulative overlay)

Slice 4 (not in this response): additional fees and penalty management screens, discounts management, consumer issues
and messages, reports, the dashboard (bills list), remaining consumer lifecycle (stop, enable, disconnect, reconnect,
delete, undo delete), bulk meter reading, and the guarded routes listed in section 1.
After Slice 4, the cumulative Phase 5 overlay will be generated from your original Phase 4 project.

**Until Slice 4 is applied, normalized mode is for testing only.** The dashboard, reports and several screens are not
available in normalized mode.

---

## 9. Rollback

Slice 3 replaces `index\views.py` and adds three files. To roll back, restore `index\views.py` from the Slice 2 result,
and delete `wb_core\services\payments.py`, `wb_core\services\ledger_view.py` and `index\business_payments.py`.
No database change is involved, so nothing in `waterbilling_v4` needs reversing. Payments already recorded stay in the
database and are never deleted by the application.
