# Phase 5 – Slice 4 (part 1 of 2): Consumer Lifecycle on the Normalized Database

**Overlay file:** `Phase_5_Slice4_Overlay.zip` (4 files)
**Apply on top of:** the Slice 3 result.

> **Read this first.** This overlay completes the **consumer lifecycle** part of Slice 4. The rest of Slice 4 is
> **not** in this overlay: the dashboard (bills list), consumer issues and messages, reports, bulk meter reading,
> fee management and fee payment screens, penalty management, and discount management. Those routes still show the
> "not available in normalized mode" message and change nothing. They are the next step.
> The cumulative package `Phase_5_Cumulative_Overlay.zip` (see `README_PHASE5_COMPLETE.md`) already contains this
> overlay, so you do not need to apply this one separately if you use the cumulative package.
> No test was run by me. No migration is in this overlay.

## 1. Files

| File | New or replaces | Purpose |
|---|---|---|
| `wb_core\services\lifecycle.py` | NEW | Stop/enable meter, exemption, disconnect, reconnect, soft delete, undelete. One transaction each. |
| `index\business_lifecycle.py` | NEW | The seven screen handlers. Same redirects and role checks as the legacy views. |
| `index\views.py` | REPLACES | Seven guards replaced by branches to the handlers. No legacy line removed. |
| `index\test_business_readings.py` | REPLACES | The routing test now uses the dashboard route, which is still guarded. |

## 2. What each operation does in normalized mode

- **Stop / enable meter:** flips the stopped flag, as legacy did. If "new meter" is ticked, it records a reset reading
  for the chosen month, creates the new meter record, attaches it to the connection, and updates the cached reading.
  A second reset for the same month is refused with a message.
- **Exempt / remove exemption:** flips the exempt flag. As legacy did, each active bill is moved out of (or back into)
  its barangay's monthly total. If that barangay summary does not exist for a bill's period, the change is refused
  with a message (legacy would have failed with an error).
- **Disconnect / reconnect:** sets the disconnected flag to on or off (not a toggle, as in legacy).
- **Delete (soft):** before the flag is set, a copy of the connection row is written to `removed_record_audit`
  (`source_table = connection`). The copy holds identifiers, flags and the cached balance. It does not hold names
  or addresses. The consumer then stops appearing in the list. Nothing is physically deleted.
- **Undelete:** clears the deleted flag. The audit copy is kept.

## 3. Differences from legacy (deliberate)

| Legacy | Normalized | Why |
|---|---|---|
| Enable with new meter used the last transaction id plus one | Not needed. Reset is an ordinary reading row | No id arithmetic |
| Legacy delete had no copy of the removed row | Copy written to the removal audit first | Recoverable history |
| Exemption failed with an error if a barangay summary was missing | Refused with a message; nothing changed | No silent partial update |
| Enable with a blank meter number was accepted | Refused | Meter number is required |

## 4. Apply (only if you are not using the cumulative package)

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Slice4_Overlay.zip"
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
```

Then `python manage.py check`.

## 5. Still not available in normalized mode (remaining Slice 4)

These routes show "not available in normalized mode yet" and change nothing:
- Dashboard / bills list (the page after login)
- Alternate ledger view
- Edit a payment (correction design is pending)
- Monthly payment screen
- Additional fees list, additional fee payment, additional fee payment history
- Delete a reading (correction design is pending)
- Add an issue (issues and messages are pending)

Reports, bulk meter reading, fee management, penalty management and discount management are not yet migrated. Some
of these may still be reachable from links that are not guarded yet. **Do not use normalized mode for real billing
until the remaining Slice 4 work and an inventory of every route are complete.**

## 6. Rollback

Restore `index\views.py` and `index\test_business_readings.py` from the Slice 3 result, and delete
`wb_core\services\lifecycle.py` and `index\business_lifecycle.py`. No database change is involved. Any soft-deleted
consumers stay deleted; undelete them through the restored undelete route, or set `is_deleted = 0` only with approval.
