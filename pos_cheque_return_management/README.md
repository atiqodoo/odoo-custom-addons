# POS Cheque Returns and Recovery

Extends POS Uncleared Payment Guard and COD Deposit Settlement. The guard reads
bank evidence; this separate addon coordinates accountant-authorized return and
recovery accounting through standard Odoo reconciliation and posted entries.

## Setup

- Install `pos_cheque_return_management` and upgrade `pos_uncleared_payment_guard`.
- Assign **Cheque Return Reporter** to staff allowed to report returns.
- Assign **Cheque Return Accountant** to accountants allowed to finalize them.
  These roles provide the relevant POS/deposit audit access; normal accounting
  permissions, company rules, journal configuration and lock dates still apply.
- Review **Customer Account Controls / Cheque Return Reasons**. Re-banking is
  configurable by reason. Suspected fraud does not permit re-banking by default.
- No fee rates, penalties or automatic customer recharges are configured by code.

## Record a return

1. Open the cheque hold and click **Record Bank Return**.
2. Select the bank's reason, explanation, original customer receipt credit and,
   when available, the actual negative bank return transaction.
3. The failed cheque becomes unavailable immediately. Prior manual clearance
   cannot release it. Unposted COD reservations funded by it are cancelled.
4. Reconcile the negative bank return to the original customer's receivable
   account for the exact principal. Separate bank expenses from customer debt.
5. On the return record, select a general journal/date for any COD corrections
   and click **Confirm Return Accounting** as a Cheque Return Accountant.

Confirmation removes only reconciliation matches involving the failed receipt,
cancels that receipt against the actual bank return, and restores its original
unpaid invoice balances. Unused deposit credit disappears; it is not invoiced as
additional debt. COD deposit applications get linked partial correction entries;
their original posted records remain unchanged. Valid independent payments are
preserved. COD cards return with only the failed allocated amount outstanding
after the normal POS refresh.

The operation is atomic and retry-safe. A missing allocation, permission error,
lock-date restriction or failed correction leaves the return pending rather than
committing half of the accounting.

## Funding provenance

Actual receipt-to-application partial reconciliation links identify COD funding
automatically. Historical applications whose links were removed require **Link
COD Funding** for the actual consumed amount. Where an application merely lists
an unused candidate credit, an accountant must explicitly document the source
review on the return instead of inventing a positive allocation. An original
application cannot have its principal returned twice through another cheque.

## Re-bank the same cheque

After return accounting, use standard bank accounting to record the actual new
positive bank credit against the original customer receivable account. Do not
create a duplicate POS deposit. On the original hold choose **Re-bank / Replace**,
select **Re-bank Same Cheque**, and identify the new customer receipt credit and
bank transaction. A separate banking attempt retains the old failed history.

The new credit remains blocked until an accountant clicks **Finalize Re-banked
Receipt**. This requires a posted, reconciled positive bank transaction. It
settles the original remaining purchase debts and eligible returned COD amounts
once; other valid payments reduce what needs settling. Cron rechecks this bank
evidence. If accounting is subsequently changed, review is required without
automatically repeating financial postings.

## Replacement cheque

Receive and bank a distinct replacement cheque through the normal workflow.
On the old returned hold select **Receive Replacement Cheque** and identify the
new hold and receipt credit. The replacement needs independently verified bank
clearance, the same customer/company/currency/principal, and its own receipt.
The old hold becomes Replaced, the funding history is linked, and recovery is
applied once. Manual clearance alone is insufficient.

## Fees and fee refunds

Select actual, separate posted/reconciled bank-expense transactions in the
return's fees tab. A refund references its original charge. If a bank combines
principal and expense in one return transaction, the inline fee is shown
separately; a later fee refund can reference that verified inline amount by
leaving the separate-charge field blank. Refund totals cannot exceed the fee.
Neither a fee refund nor its positive bank amount clears cheque principal.
Customer recovery charges, if approved, use normal customer invoicing separately.

## Scope and history

- Customer incoming cheques only. Credits returning the business's own outgoing
  cheques are not incoming customer payments or customer-cheque returns.
- Company currency and whole-principal returns, with one exact customer receipt
  credit per attempt. Aggregated credits and foreign currency require accountant
  preparation; they are not inferred from amount or reference text.
- Re-banked direct bank credits must use the original receivable ledger so an
  unused ordinary deposit is not stranded in a COD account.
- Source references, fees, bank imports and posted accounting history are not
  deleted or overwritten. Existing holds are not automatically reported bounced.
- Negative bank imports do not guess a return reason. A user explicitly reports
  the return; an accountant confirms its correction.
- No historical bank transaction is relabelled automatically on installation.

Python operations log safe record IDs with `[CHEQUE][OPERATION][START/END/ERROR]`
headers. Customer banking details and return explanations are not logged.
