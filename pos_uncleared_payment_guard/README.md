# POS Uncleared Payment Guard

Standalone POS control addon for holding mapped Customer Deposit / Settle Due
payments from usable customer balance until cleared.

## Boundary

This addon does not post, modify, or reconcile accounting moves. It only:

- creates `pos.uncleared.payment.hold` audit records for POS-mapped or globally marked guard methods
- adjusts POS credit/deposit availability exposed by `pos_credit_limit`
- marks holds cleared from read-only reconciliation detection or an authorized backend wizard

## Accounting confirmation after manual clearance

Manual clearance releases the POS balance restriction; it does not reconcile
accounting. Once the detector finds accounting clearance, both ordinary deposit
holds and COD collection holds advance from Manually Cleared to Accounting
Cleared. The detected transfer and bank statement are saved on the hold.
Finding only a transfer keeps a manual hold released while awaiting bank
clearance. Cancelled holds are not reprocessed. Linked accounting confirmations
are rechecked so removing a reconciliation invalidates their bank evidence.

## Link Transfer workflow

1. Record the normal POS receipt and post its session accounting.
2. Record one transfer per whole cheque: credit the collection account and debit
   the destination bank's configured, reconcilable Outstanding Receipts account.
3. On the hold, click **Link Transfer** and select that posted entry. No special
   reference is required. This needs the Uncleared POS Payment Manager role and
   existing access to the selected accounting entry.
4. Reconcile the bank receipt against the transfer's Outstanding Receipts line.
5. Click **Check Accounting Now**, or allow the scheduled checker to run.

The checker follows actual partial-reconciliation links from the selected
transfer to incoming, reconciled transactions in the selected bank. It can sum
multiple linked bank receipts, but only clears the whole cheque once its full
amount is confirmed. It never uses equal amounts, reference text, or customer
receivable reconciliation alone as proof of bank clearance.

This version supports company-currency, two-line transfers and direct bank
statement entries crediting the collection account. Combined-cheque transfers,
foreign-currency cheques and intermediate multi-journal payment chains must be
handled separately; they are not guessed. A transfer cannot clear two holds.

Existing detected references are preserved during upgrade but are not treated
as an explicit selection. Pending/manual holds need **Link Transfer**. Historic
Accounting Cleared holds without an explicit link retain their existing state;
they are not automatically reclassified or backfilled. When a new linked
confirmation is undone, the hold returns to Manually Cleared if a manager had
authorized it, otherwise Transfer Seen. The checker never changes ledger entries.

## Debugging

Python logs use logger names under `pos_uncleared_payment_guard.*`.
Browser logs use the `[UPG]` prefix and are controlled by
`pos.config.upg_debug_logging`.
