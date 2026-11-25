# Phase 5 – Slice 4B (part 2): Consumer Issues and Messages on the Normalized Database

**Overlay:** `Phase_5_Slice4B_Issues_Overlay.zip` (3 files)
**Apply on top of:** the Slice 4B Part 1 state (Slices 1 to 4A and Slice 4B Part 1 applied).

> **Read this first.** This part completes **consumer issues and issue messages**, and closes legacy routes that
> still wrote to the legacy tables. It does **not** complete Slice 4B. Still to do: reports, bulk meter reading, fee
> management and fee payments, penalty management, discount management, payment edit (correction), and reading delete.
> Those routes still show a message and change nothing. No test was run by me, and no migration is included.

## 1. Files

| File | New or replaces | Purpose |
|---|---|---|
| `wb_core\services\issues.py` | NEW | Raise an issue, list and search, messages, mark read, resolve (no deletion) |
| `index\business_issues.py` | NEW | Issue screens: add (from the reading screen), list, details, post message, resolve |
| `index\views.py` | REPLACES | Four issue routes switched; the add-issue guard replaced; the additional-fee route guarded |

## 2. What changed in behaviour

- **Adding an issue** saves an issue reading for the month, marked as an issue flag. It never changes a bill, a payment
  or a balance. If an earlier issue reading exists for that month, it is marked **superseded** (kept, not overwritten).
- **Issue list and search** use the same search rules as before (consumer number, meter number, issue text, names).
- **Issue details** mark the issue as seen and mark messages from other users as read, as before.
- **Posting a message** keeps the same routing: a reply by the issue owner goes to the last sender; otherwise it goes to
  the issue owner. It also updates the issue's last comment, which legacy tried to do and never did.
- **Messages** are limited to 100 characters, the stored size. A longer message is **refused**, not cut short.
- **Resolving** marks the issue `Resolved`. **Legacy deleted the issue and its reading** (and reset the consumer's
  reading). The normalized version deletes nothing; the reading and messages stay as history. Resolving twice is refused.
- Permissions are unchanged: any logged-in user can raise, read and message issues, as before.

## 3. Legacy routes closed in this part

- **Post a message** and **resolve an issue** had no guard in the previous checkpoint. They are now normalized.
- **Additional fee creation** (`additional_fee`) wrote to the legacy fee table without a guard. It is now guarded and
  shows "not available in normalized mode yet" until fee management is migrated.

## 4. Apply

```powershell
$Z = "C:\Users\chuan\Downloads\Phase_5_Slice4B_Issues_Overlay.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::OpenRead($Z).Entries | ForEach-Object { $_.FullName } | Sort-Object   # expected: 3 lines
Expand-Archive -LiteralPath $Z -DestinationPath "C:\Users\chuan\Downloads\JANICEEEE\waterbillV4" -Force
```

## 5. Rollback

Restore `index\views.py` from the Slice 4B Part 1 state, and delete `wb_core\services\issues.py` and
`index\business_issues.py`. No database change is involved. Issue rows already written stay in `issue` and
`issue_message`, and the application never deletes them.

## 6. Still to do in Slice 4B

Reports; bulk meter reading; fee management and fee payments; penalty management; discount management; payment edit
(correction); reading delete (correction). Then the complete Slice 4 overlay and the cumulative overlay.
