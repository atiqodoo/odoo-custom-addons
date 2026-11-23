# Variant price adjustment, version 18.0.2.0.0

Automatic changes update native **variant fixed-price pricelist rules**. Product
template sale prices, shared rules, accounting cost, valuation layers and existing
order-line prices are not written by the pricing service.

The service resolves native rule precedence and current quantity tiers before
writing any overrides. Shared fixed rules receive variant-specific overrides with
their source validity dates. Formula/percentage rules cause that variant/pricelist
adjustment to be skipped and logged for review. A missing rule is also skipped
unless **Allow Standard Sale Price Fallback** is explicitly enabled. This avoids
silently using a default sale price of 1.

Purchase-tax comparison uses bill-line taxes, linked purchase-order taxes for
receipts/landed costs, or company-specific product purchase taxes as fallback.
Mixed tax treatments for the same variant in one source require manual review.
Old and new accounting costs are evaluated under the same current tax treatment;
tax configuration changes alone do not trigger a price increase. The legacy VAT
percentage field is retained for compatibility and is no longer used.

Cost baselines are company/variant/pricelist specific. They retain the last
successfully processed tax-exclusive cost (not a margin or inventory valuation).
Cost decreases do not lower prices or reset the baseline. No new minimum change
threshold is introduced. The configured upward rounding step remains in company
currency; increments are converted to the target pricelist currency.

All enabled POS configurations in the event company are considered. A shared
pricelist is adjusted once. Conflicting enabled policies or use of the same
pricelist by another company cause a logged skip. Database row locking,
transaction retry propagation and per-pricelist savepoints protect adjustments.

Native pricelist-rule create/write/delete operations publish private POS bus
notifications after commit. Connected terminals fetch authorized rules, replace
stale rules and rebuild native price caches. Startup, reconnect, tab activation
and the configurable recovery interval catch missed notifications. Offline
terminals retain cached prices and show a warning until synchronization succeeds.
No cost information is sent by the new snapshot endpoint. Existing order lines
are not repriced by synchronization.

## Apply to the development service

Run in an **Administrator PowerShell**:

```powershell
& C:\odoo18\custom_addon\pos_auto_variant_price_rounding\tools\apply_update.ps1 -Database 'dev_prod_test_2026-11-10_21-50-35'
```

The script verifies the service configuration, stops the development service,
makes a PostgreSQL database backup, upgrades only this addon, and restarts the
service. Reload each POS browser once to load the new code. Subsequent price
updates synchronize automatically. Do not apply while cashiers are completing
transactions.

No historical price repair or baseline backfill is performed. Legacy tracking
fields and external IDs are retained. New baselines begin from the first event's
pre-operation cost, avoiding reinterpretation of the old fixed-VAT baseline.

## Validation

Backend tests: Odoo `--test-tags=/pos_auto_variant_price_rounding`, preferably in
a disposable database. Frontend method tests:

```powershell
node custom_addon/pos_auto_variant_price_rounding/tests/price_sync.test.cjs
```
