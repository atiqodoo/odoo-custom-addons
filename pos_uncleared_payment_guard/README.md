# POS Uncleared Payment Guard

Standalone POS control addon for holding mapped Customer Deposit / Settle Due
payments from usable customer balance until cleared.

## Boundary

This addon does not post, modify, or reconcile accounting moves. It only:

- creates `pos.uncleared.payment.hold` audit records only for methods mapped on the active `pos.config`
- adjusts POS credit/deposit availability exposed by `pos_credit_limit`
- marks holds cleared from read-only reconciliation detection or an authorized backend wizard

## Debugging

Python logs use logger names under `pos_uncleared_payment_guard.*`.
Browser logs use the `[UPG]` prefix and are controlled by
`pos.config.upg_debug_logging`.
