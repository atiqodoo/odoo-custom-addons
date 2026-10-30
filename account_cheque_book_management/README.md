# Cheque Book & Vendor Payments — Odoo 18

Manages company-owned physical cheque books and outgoing vendor cheques. This
addon is independent of `pos_cheque_return_management`; that addon remains the
incoming customer-cheque workflow and is not modified or required.

## Installation and configuration

1. Update the Apps list and install **Cheque Book & Vendor Payments**. Dependencies
   are `account_check_printing` and `mail` (Accounting is a transitive dependency).
2. Assign **Cheque Book Manager** to the administrator of books/policies,
   **Cheque Book Accountant** to financial approvers and **Cheque Book Operator**
   to preparers/custodians. Existing accounting permissions and company rules apply.
3. Open Accounting / Configuration / Journals. Select the bank journal, configure
   its company-owned bank account, and enable **Manage Physical Cheque Books** in
   the new **Cheque Books** tab.
4. Enable the standard **Checks** outgoing payment method. Configure its separate,
   reconcilable outstanding-payments account. Do not use the bank liquidity account
   as the outstanding account.
5. Optionally configure **Cheque Validity (Days)**. Zero means the accountant
   reviews validity manually. Enable **Require Separate Preparer and Approver**
   when another accountant must approve a prepared payment.
6. Create a book from the journal tab or the **Cheque Books** app. Enter its
   reference, first cheque number, positive leaf count, date and custodian.
   Activate it to generate the exact numbered range. Leading zeros are retained;
   overlapping numbers are rejected even across journals sharing the bank account.
7. Configure return reasons in the app. Re-presentation is disabled unless the
   selected reason explicitly permits it. No penalties, bank fees, validity periods,
   bank identities or approval amounts are seeded by code.

After activation, the range, journal bank identity and generated leaf identifiers
are protected. Suspending/closing a book blocks new reservations; existing issued
cheques and their accounting remain available for resolution.

## Paying vendor bills

Each cheque book now has a **Bank Code** field for the bank/branch code printed
on its leaves. Enter it as printed, preserving leading zeros and separators.
A Cheque Book Manager can maintain this field on existing active books. Each
newly confirmed banking attempt snapshots its code so later profile corrections
do not rewrite the historical confirmation.

In **Pay**, select the bank journal and **Checks**, then select **Cheque Book**,
**Cheque Leaf**, and **Cheque Date**. The same fields appear on standalone vendor
payments. The physical leaf is authoritative for the standard Odoo cheque number.
Ordinary payments on journals without cheque management retain standard behaviour.

Upload **Completed Cheque Copy** in the bill-payment wizard. It is transferred to
the resulting payment as private, record-bound evidence. On standalone payments
you can save a draft first, but confirmation is blocked until the completed-cheque
copy is uploaded. A blank sample leaf is not the completed payment evidence.
Re-presentations and replacements each require an upload in **Cheque Action**.
Confirmed/cancelled evidence cannot be edited, deleted, made public or reassigned,
including through direct attachment operations. Existing posted payments are not
rewritten or retroactively required to upload a copy.

One payment uses one leaf. Group compatible bills for one vendor to pay with one
cheque. A registration producing multiple payments is rejected with an explanation;
register those separately, choosing an individual leaf for each payment.

Saving reserves the leaf atomically. A second reservation is rejected. Protected
payment details cannot be silently changed or reset after reservation. Void the
instrument and prepare another if the physical details must change.

An accountant confirms the payment; the attempt records approver/date. If separate
approval is enabled, the Pay wizard creates a draft with its intended bill links.
Bills remain open until a different Cheque Book Accountant confirms it through
**Awaiting Approval**. Changed bill balances block overpayment at approval.

Open the linked leaf and use **Cheque Action** to confirm authorised signature,
then record handover and the vendor receipt reference. Attach scans/evidence in
the leaf/book chatter using standard Odoo attachment access controls. These are
audit confirmations, not electronic signatures or bank authorisations.

## Bank clearance

Reconcile the actual negative bank transaction against the cheque payment's
outstanding-payments line. On the leaf use **Confirm Bank Clearance**, selecting
that exact transaction. Posting, printing, signing and handover do not establish
bank clearance. Future-dated instruments cannot be confirmed cleared before their
date. A scheduled review flags changed bank evidence without repeating postings.

## Damaged and cancelled leaves

- **Mark Unused Leaf Damaged** consumes an available unused leaf permanently.
- **Void / Cancel Recovered Cheque** consumes a leaf permanently. For a prepared
  cheque, confirm recovery/destruction or a confirmed bank stop-payment.
- For an issued but uncleared cheque, voiding reverses only its payment and reopens
  its settled bills. A cheque already debited by the bank needs the bank-return
  workflow. A reserved draft retains its audit/payment record and cannot be posted.
- **Request Stop-Payment** records the request. **Confirm Bank Stop-Payment**
  requires a bank confirmation reference. These actions record external evidence;
  the app does not submit instructions to a bank.

## Returned / bounced cheques

1. **Report Bank Return** with a reason and explanation. If already reconciled at
   the bank but not yet marked cleared, also select the original negative bank
   transaction. The leaf is blocked immediately; reporting alone changes no ledger.
2. An accountant selects an open correction date and **Confirm Return Accounting**.
3. For an uncleared cheque, the original outstanding payment is reversed. No bank
   principal refund is invented.
4. For a cheque already debited, first reconcile the actual positive principal
   return to the outstanding-payments account, and select that bank transaction.
   It must contain the exact principal; record fees separately.
5. Only reconciliations involving the failed payment's payable line are removed.
   Other valid payments survive. Standard Odoo reversal entries preserve the posted
   original and reopen the affected liability. Failure rolls back the complete action.

Repeated correction does not create another reversal. The app never creates a
second vendor bill or duplicates an expense to represent a bounced cheque.

## Re-presentation and replacement

**Re-present Same Cheque** creates another attempt and a new payment under the
same physical leaf after the previous return is accounted for. It preserves the
original cheque date, validates the configured validity policy and return reason,
and rejects instruments with stop-payment or replacement. Reduced unpaid bill
balances require a replacement rather than changing the face amount. Re-presenting
does not consume another leaf.

**Issue Replacement Cheque** consumes an available leaf from the same bank journal.
Resolve the original accounting, then confirm physical recovery/destruction or
bank stop-payment. Explicitly enter the remaining amount; it cannot exceed the
original principal or remaining linked bills. The old leaf becomes Replaced and
the new one links back to it. Approval policy also applies to new recovery payments.

## Actual bank fees and refunds

Use **Bank Fees / Refunds** to link separate posted, reconciled bank expenses or
expense refunds to an attempt. A refund references its original charge; cumulative
refunds cannot exceed it. These records do not post a second expense and cannot
clear principal. Principal and fees combined on one imported transaction must be
prepared as separate transactions by an accountant before this workflow.

## Reports, security and operation

Books show available leaves and unresolved leaves. The register includes current
vendor/principal/status. Issued / Uncleared has a currency-grouped pivot; Returned
Cheques and Awaiting Approval have dedicated menus. Attempt history retains all
presentations and approval/signature/receipt/stop/reversal evidence. Events cannot
be edited or deleted. Standard Odoo export is available for authorised users.

All custom company records have allowed-company rules. Financial transitions check
roles server-side. An in-process capability protects internal transitions; a caller
cannot bypass it by passing a truthy context flag. Parameterised row locks serialize
reservation, activation and recovery. No business workflow uses `sudo()`.

Backend operations use `[CHEQUE_BOOK][OPERATION][START/END/ERROR]` debug headers with
record/company/user IDs only. Exception logs record the error type rather than
financial descriptions, account numbers or private explanations. Chatter/events
retain authorised business evidence separately from backend logs.

## Current boundaries

- Company-currency cheques and bank journals only; full-principal returns.
- One exact payment/principal per bank transaction; aggregated statement amounts,
  write-offs and mixed principal/fee imports require accountant preparation.
- The standard cheque layout must be configured for optional printing; no
  bank-specific physical print layout is supplied. Number selection works for
  handwritten cheques as well. Managed printing does not allocate another number.
- Standalone vendor advances are supported as unapplied payable payments. Physical
  delivery receipts can be attached; no Purchase/Stock integration is installed.
- Approval uses roles and optional separate approval, without monetary approval tiers.
- Existing cheques/books are not inferred, renumbered, migrated or reclassified.
- Installation in an existing business database is a separate deployment step.

## Validation

Run this addon's post-install suite against a dedicated test database, for example:

```powershell
C:\odoo18\python\python.exe C:\odoo18\server\odoo-bin `
  -c C:\odoo18\config\odoo-dev.conf -d YOUR_ISOLATED_TEST_DATABASE `
  --no-http --stop-after-init -i account_cheque_book_management `
  --test-enable --test-tags /account_cheque_book_management `
  --without-demo=all --max-cron-threads=0
```

Tests cover books, ranges, reservation, payment forms, bill grouping, bank evidence,
returns before/after clearance, rollback, other payments, re-presentation,
replacement, signatures, stop-payment, fees, permissions, companies and approvals.
