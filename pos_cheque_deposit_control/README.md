# POS Cheque Deposit Control

Extension of `pos_uncleared_payment_guard`. Due cheques have a separate POS
banking reminder. Cheque deposit transfers require an explicit cheque selection,
actual deposit date, and uploaded bank receipt before posting.

## Installation and setup

1. Upgrade `pos_uncleared_payment_guard` to load its reusable transfer validator.
2. Install `pos_cheque_deposit_control`.
3. On each cheque payment method, enable **Cheque Deposit Control**. Use a
   dedicated cheque collection journal/account. Do not share this account with
   non-cheque payments: entries cannot reveal which payment type used a shared
   account. Keep the existing uncleared guard mapping enabled.
4. On each applicable POS configuration, select one or more **Allowed Deposit
   Bank Journals** in the existing uncleared-payment settings. Each bank must
   have its own configured, reconcilable inbound Outstanding Receipts account.
5. Enable **Cheque Banking Reminders and Receipts** and set the positive refresh
   interval in seconds (initial default: 60). Set **Repeat Banking Popup After
   (seconds)** separately (initial default: 300, or five minutes). POS managers
   control these settings. Both intervals must be positive.
6. Users posting cheque deposits need standard accounting posting permissions
   plus **Uncleared POS Payment Manager**. Cashiers need POS user access only to
   view their POS's company-bound reminder projection.
7. Reload POS after changing configuration or installing assets.

Nothing selects production account IDs or journals automatically. Existing POS
configurations stay disabled until a manager explicitly configures them.

## Posting a cheque deposit

1. Create and save a draft journal entry, one complete cheque per entry.
2. Credit the cheque collection account and debit the selected bank's configured
   Outstanding Receipts account. The existing internal-transfer clearing route
   and direct bank statement route remain subject to the base validator.
3. Select **Cheque Being Deposited**. The hold records the destination bank.
4. Enter **Actual Cheque Deposit Date** and upload **Bank Deposit Receipts**.
   Save a new entry before uploading so attachments belong to that saved entry.
5. Post. The server validates company, permissions, company currency, two-line
   accounting, whole amount, bank, dates, and private nonempty uploaded files.
   It then uses the existing transfer-link workflow. Failure rolls back posting.

For configured collection-to-bank account pairs, leaving the cheque field blank
does not bypass the receipt rule. Reverse-direction and unrelated entries are
unaffected. Enforcement applies to state transitions used by UI, `_post`, cron,
imports, and direct ORM/RPC writes, and to accounting edits of posted entries.

The actual deposit date must be on/after the cheque date and no later than today.
It does not have to equal the accounting date. An uploaded receipt is evidence
supplied by the operator, not automatic verification by a bank.

## Reminder lifecycle

- Cheque date today or earlier, positive amount, not cancelled, and no validated
  linked posted deposit with receipt: show the banking reminder.
- Future cheque: wait until due.
- Draft transfer or manual balance release: keep the reminder.
- Valid posted transfer with receipt: remove the banking reminder. Existing
  uncleared-payment controls continue until bank clearance or manual release.
- Reset/cancel/reverse the transfer: restore the banking reminder. Resetting to
  draft detaches its old link; reposting validates and links it again.
- Receipt content and accounting lines cannot be replaced/deleted while posted.
  Standard accounting authorization governs resetting and correcting an entry.

The banner refreshes at startup, after POS synchronization, on browser reconnect,
and at the configured interval. When a successful check finds due cheques, the
reminder automatically opens as a modal and blocks interaction with the POS
behind it. The cashier must dismiss it using the header X; Escape and backdrop
clicks do not dismiss it. This applies on desktop and mobile. Dismissal resumes
normal POS interaction, including barcode scanning, which is paused while this
modal is open. Dismissal also starts
the separate popup repeat interval. At expiry, status is checked again and the
modal reappears if cheques remain due. Background checks do not interrupt this
dismissal interval, and only one reminder can be open at a time. If no cheques
remain due, the modal does not reappear. Reopening POS starts a fresh check.

A failed refresh keeps the last count and marks
it stale. Details are paginated; the count covers all due records, not just the
current page. Reminders cover all sessions of the current POS, including closed
sessions. They do not expose receipt files, account numbers, or customer details.

Existing posted entries are not migrated or automatically modified. Historical
holds without the required linked receipt evidence can appear as needing review
when control is enabled; verify historical deposits rather than fabricating links.
Existing combined-cheque and foreign-currency limitations remain unchanged.

## Architecture and security

- `cheque_deposit_policy`: configured scope; no account numbers or journal names
  are hardcoded. Accounting checks read POS configuration with narrowly scoped
  elevation, but entries/receipts retain caller permissions.
- `cheque_deposit_validation`: one authoritative deposit evidence check, reusing
  the base addon's `_upg_validate_transfer_move` accounting contract.
- `account_move`, `ir_attachment`, `hold_transfer_link`: posting, lifecycle, and
  evidence protection, without granting extra accounting permissions.
- `cheque_deposit_reminder`: authorized POS projection; explicit POS/company
  filtering before elevation. A global hold rule enforces allowed companies.
- `static/src/app`: lifecycle-managed banner refresh and paginated details.

New logs use `[PCD][OPERATION][START|END|ERROR]`, with record IDs and outcomes.
They do not log cheque account numbers, uploaded contents, or full POS payloads.
Expected rejections are logged at debug level. The inherited addon's existing
logging behavior is unchanged.

## Tests

Run against a disposable database with the required dependencies installed:

```text
odoo-bin -d <test_database> -u pos_uncleared_payment_guard,pos_cheque_deposit_control --test-enable --test-tags /pos_uncleared_payment_guard,/pos_cheque_deposit_control --stop-after-init --no-http
```

Use `-i pos_cheque_deposit_control` on first installation. Tests cover normal
posting, unrelated entries, multiple banks, same-amount cheques, due dates,
invalid/missing evidence, state-write bypasses, posted-entry edits, correction,
reversal, permissions, company isolation, and totals independent of pagination.

Client lifecycle tests (startup, timers, reconnect, synchronization, stale data,
pagination, and cleanup) run without a browser:

```text
node --test custom_addon/pos_cheque_deposit_control/tests/reminder_client.test.mjs
```
