# Vendor bill price entry

The normal and combined LPO bill wizards share the same **Vendor Price Basis**
calculation. Standard vendors can enter unit/list prices as **VAT Exclusive**
(the existing default) or **VAT Inclusive**. Purchase managers can set a default
on the commercial vendor. Child contacts use that commercial vendor's default.

The selection applies before the existing discount and freight adjustments.
Enter zero adjustments when the printed vendor price already includes them.
The final vendor invoice total always includes VAT.

Configured formula profiles, including Crown and Gamma, retain their own
calculations. Inclusive standard entry is hidden and rejected server-side for
these profiles. Existing bills and stored audit records are not reinterpreted.

Inclusive entry extracts tax with Odoo's tax engine using each purchase line's
mapped taxes. Configure explicit zero/exempt taxes for exempt lines. This flow
expects tax-excluded purchase taxes, because the generated bill unit prices
remain exclusive. Shared tax configuration is never changed by the wizard.

## Precision and rounding

The extracted unit price retains precision until bill creation. Odoo's configured
**Product Price** decimal accuracy still controls the persisted bill unit price.
The wizard blocks creation when this precision would change the calculated
inclusive line total; increase decimal accuracy in Settings and reopen the
wizard. Six decimal places are sufficient for the supplied 26.00 / 24-unit
example, but the required precision depends on prices, taxes and quantities.

Company tax rounding remains authoritative. For example, with per-line rounding,
26.00 inclusive at 16% for 12 units becomes 268.97 base + 43.04 tax = 312.01.
With global rounding it becomes 312.00. Such native rounding differences remain
visible through the existing invoice variance policy. The wizard does not
silently override tax amounts to force printed totals to match.

Bill lines retain the entered unit price, its basis, and the computed exclusive
unit price. Formula lines are marked **Controlled by Vendor Formula**. Original
input and exclusive audit unit fields retain precision rather than currency
rounding. Price/basis edits invalidate approvals, and changed tax inputs require
fresh acknowledgement/approval when applicable.

## Upgrade and verification

Upgrade `purchase_net_price_compute`, `vendor_price_check`, and
`vendor_combined_lpo_bill_wizard`, then restart the Odoo process loading these
Python models. No company precision or tax settings are changed by the upgrade.

The Odoo tests cover both wizard paths, bill creation/posting, the PIJ brush
example, zero/mixed taxes, formula regressions, insufficient precision, partial
receipts, native rounding, stale approvals, permissions and company boundaries.
