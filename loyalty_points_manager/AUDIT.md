# Loyalty calculation audit

Upgrade `loyalty_points_manager` to load the new models, security and views, then
restart Odoo with the updated Python code. No existing points or policies are
recalculated by this upgrade. Historical rows are not backfilled as original evidence.

## Access and navigation

Sales Managers inherit the **Loyalty Audit** group. Administrators can assign this
group separately to authorized auditors. Audit events, lines and condition results
are read-only through user ACLs and restricted to allowed companies. Internal
award workflows create them through a private server method.

Open **Loyalty Points > History Logs**, then a transaction. The standard history
form used by card/order links also includes the audit tabs:

- **Order Line Audit**: every source line, frozen quantity/UoM/amount, allocated
  base share, actual tier contribution, posted points and redemption costs.
- **Audit Events**: open an event for balance before/after, tier evaluation,
  payment/gate details and the full source/rule snapshot.
- **Current Source Lines**: live reference values, subject to source-order access.
  These are explicitly not historical earning evidence.

**Loyalty Points > Audit Events** also retains evidence after Sales cancellation
removes the standard history. Cancellation entries show the actual signed net
card movement and compare it with the expected reversal of the original events.
The audit does not change the existing cancellation accounting/points behavior.

## Meaning of amounts

The existing earning engine remains authoritative. It collects tier evaluations,
matched product rules, UoM conversion and fallback results during the calculation.
The audit writer does not calculate a second earning result.

Base points arrive as an order total. Per-line base shares are explicitly labelled
allocations using signed source amounts, not independent base-rule awards or proof
of base eligibility for each line. Full base-rule settings are saved with the event.
Unallocated amounts and rounding differences appear on an order-level
reconciliation row. Source lines include discounts, rewards and Sales notes.

Mixed POS transactions preserve gross `issued` and `used` in history instead of
representing only their net difference; the actual card movement is unchanged.
Event/line totals reconcile to the posted issued/used amounts.

Sales confirmation redemptions and later delivered/invoiced/paid earning awards
are separate events even when they share one history row. COD events capture the
cumulative paid ratio, prior awards and delta. Their line amounts are explicitly
allocated collection deltas; full-order points remain available in the line form.
Frozen COD snapshots retain the original source lines and rules. `evaluated_at`
records when the existing workflow actually evaluated/froze the calculation
(currently the first collection when an earlier snapshot does not exist).

An old COD snapshot without full calculation evidence is marked partial. Historical
transactions without evidence are marked unavailable; opening them never resolves
today's tier as though it were the original decision. A difference between saved
events and history totals also marks the capture partial.

## Validation

Run Odoo with `--test-enable --test-tags=/loyalty_points_manager --stop-after-init`
against an isolated database. Tests cover tier gaps, actual rule/fallback results,
immutable snapshots after configuration edits, reconciliation, new/existing POS
cards, duplicate confirmation, earning/redemption, Sales award aggregation, COD
instalments, legacy evidence, rollback on audit failure, permissions, companies,
HTML escaping and compiled form/action selection.

Structured backend debug boundaries use `[LPM][AUDIT]` and `[LPM][TIER_AUDIT]`.
Full calculation snapshots stay in audit records rather than operation logs.
