# Posted vendor bill costing — 18.0.1.4.0

New AVCO POS oversells retain their original provisional unit cost. A supplier
receipt reserves the actual negative quantities it replenishes, in core FIFO
order, including older non-POS shortages and lot boundaries. Replenishment and
financial finalization are separate states.

No custom price difference is finalized from a purchase order or draft bill.
Both a completed supplier receipt and a posted, purchase-linked vendor bill are
required. Either event can happen first. Partial receipts and partial bills
finalize only their common quantities. All received quantities participate in
bill matching, including ordinary inventory, so bill quantities cannot be reused.

Cost follows the posted bill's stock_account gross unit price (discounts/taxes),
accounting exchange rate, and product UoM. Stored custom net_price fields are not
an independent accounting authority. A legitimate zero-price line is supported.

## Accounting ownership

For new tagged POS shortages only, core FIFO vacuum still consumes physical
quantities but defers its receipt-price correction using a zero-value marker.
Core bill valuation treats the owned billed portion as a stock correction instead
of also expensing it as already-out stock. Finalization creates the complete
bill-minus-original variance in the category price difference/stock accounts,
with a matching correction SVL and an AVCO refresh. Other quantities and tinting
consumption remain under their existing accounting owners.

When a bill precedes a receipt under the received-quantity invoice policy, Odoo
can still use the PO receipt cost. An additional, linked stock/input correction
brings only the owned billed units to the posted bill basis first. Corrections
already made by stock_account are recorded and deducted so they are not repeated.

Example: provisional 100, PO 120, posted bill 125, one unit:

* Receipt: stock value still contains a provisional difference of 20; no POS
  price-difference entry is finalized.
* Bill: core adjusts stock by 5; the POS settlement debits price differences 25
  and credits stock 25. Stock valuation and the stock ledger return to zero.

## Operations and access

Inventory > Reporting > POS Negative Stock > Posted Bill Cost Allocations shows
reserved quantity, finalized quantity, missing purchase linkage, and errors.
Accounting managers can retry finalization. A failed journal rolls back its
settlement, valuation correction and finalized quantity together; the vendor bill
can remain posted, and the error stays visible. No accounting posting uses sudo.
Internal allocation/valuation bookkeeping uses scoped elevated writes, as core
stock_account does, after authorization of the source operation.

Row locks serialize receipt ownership and PO-line billing allocation; a separate
allocation lock and unique settlement key prevent duplicate finalization.
Company rules protect allocations, matches, settlements, and reconciliation logs.
The persistent bookkeeping models are read-only to ordinary application users.

## Cutover and correction limitations

Upgrade the addon and restart its Odoo instance. Existing tagged layers and
posted entries are not automatically migrated or recomputed. Historical open
layers require a separately reviewed migration with their existing accounting.
The new flag applies only when a new negative POS layer is first tagged.

Affected credit notes, receipt/POS returns, bill resets/cancellations, and direct
settlement reversals are blocked for accounting review. This version does not
provide an automatic reversal/reallocation wizard; implementing that lifecycle
requires explicit quantity and price-only credit-note policies. Do not bypass
these guards or delete allocation records to force a correction.

Unlinked receipts remain visible for review and never fall back to PO cost.
No cron backfill of historical transactions is enabled.

## Validation

Run the addon's post-install Odoo tests on an isolated database. Tests cover
receipt/bill order, partial billing and receipts, separate receipt prices,
ordinary stock, mixed shortages, discounts, zero/equal costs, currency/UoM,
posting failures/retries, missing accounts, lot matching, access rights, company
isolation, legacy cutover, and correction guards. Tests compare ledger/SVL totals
for the accounting paths, rather than only checking helper return values.
