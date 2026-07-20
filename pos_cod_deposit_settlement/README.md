# POS COD Deposit Settlement

This bridge addon applies posted, cleared credits on the customer's default
Odoo receivable account to the dedicated COD receivable account.

Accounting entry:

- Debit default customer receivable
- Credit COD receivable

Both sides are reconciled in the same database transaction. No cash, bank,
M-Pesa, cheque, `pos.payment`, or `pos.cod.collection` record is created.

Normal posted non-COD POS invoices paid through Customer Account are classified
as eligible deposit-consumption debits. They join the source deposit credits and
the new bridge debit in the default-receivable reconciliation group. Unrelated
or overdue receivable debits remain blocked.

## Same-session deposits

Validated deposits in an open POS session are reserved against their source
`pos.payment` records. The COD card remains visible as `partial` with a pending
reservation badge. During session close, standard POS accounting runs first;
the reservations then create and reconcile their COD bridge entries in the
same RPC transaction. Any finalization error rolls back the complete close and
returns a structured POS alert.

## Deliberately deferred

- Returns and reversals
- Draft or browser-unsynced deposits
- Foreign-currency settlement
- Cross-company settlement

## Extension and load-order boundary

The addon depends on `pos_uncleared_payment_guard`, which already depends on
`pos_cod` and `pos_credit_limit`. Its backend extensions therefore load after
the existing COD discount/open-balance implementation and call `super()`.

The POS patch does not override the contested `processCod`,
`cod_collect_payment`, or `cod_fetch_pending_orders` methods used by the
M-Pesa, credit-note, loyalty, and uncleared-payment addons. It adds only the
unique methods `onApplyCustomerDeposit`, `cddsGetCodDepositQuote`, and
`cddsApplyCodDeposit`.

## Debugging

Server logger names:

- `pos_cod_deposit_settlement.config`
- `pos_cod_deposit_settlement.audit`
- `pos_cod_deposit_settlement.pos_order`

Server messages use `[COD-DEPOSIT]` plus stage markers such as `[BALANCE]`,
`[LOCK]`, `[MOVE]`, `[RECONCILE-DEFAULT]`, `[RECONCILE-COD]`, `[SUCCESS]`, and
`[ERROR]`. Browser messages use `[COD-DEPOSIT-UI]`.
