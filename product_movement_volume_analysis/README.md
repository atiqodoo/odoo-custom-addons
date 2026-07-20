# Product Movement Volume Analysis

This addon complements `enhanced_stock_card`. The stock card remains the detailed
quantity/value ledger; this addon provides cross-product movement analytics using
completed stock move lines, UoM normalization, reporting grades, pivots, graphs,
and an Odoo Enterprise spreadsheet dashboard.

## Design

- One immutable fact per completed `stock.move.line`.
- Transaction quantity is converted with Odoo's UoM engine into the UoM
  category reference unit (for example, 3 x 4L becomes 12 L).
- Operation family and business channel are independent dimensions.
- Product grade is derived from exactly one product tag marked as a reporting grade.
- Hook failures never block warehouse validation; the scheduled reconciliation job
  safely creates missing facts later.
- POS facts are enriched after the POS order is linked to its picking, because Odoo
  completes the stock move before writing that relationship.
- Users have read-only access to facts. Managers can run the backfill wizard.

## Diagnostics

Logger namespace:

`odoo.addons.product_movement_volume_analysis`

Fact logs contain the stock move and move-line identifiers, source, operation,
channel, transaction quantity, conversion ratio, normalized quantity, and grade.
