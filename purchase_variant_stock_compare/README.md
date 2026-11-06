# Purchase Variant Stock Compare

Adds **Compare Stock** to saved product lines on draft/sent RFQs, including
automatic RFQs. The button opens a standard Odoo dialog; it never replaces a
product or changes purchasing quantities.

## Matching and quantities

- Reuses Modern Quotation Catalogue category-filter and colour/attribute-group
  resolution. Mapping records remain the authoritative equivalence data.
- Applies purchase eligibility, exact stock UoM, selected category descendants,
  and the selected colour/attribute group. Always defaults to the product's own
  category, even if a catalogue category group is mapped. Check **Use Category
  Group**, select the group, then click **Refresh Stock** to compare across its
  mapped categories. Uncheck it and refresh to return to category matching.
  Pack/stock UoM and colour matching apply in both modes.
- First matches the colour group, or the original colour code/all original
  attribute values when no group is selected. If there are no matching alternatives
  besides the original (including products with no colour/attributes), falls back
  to the same category scope and exact stock UoM. With **Use Category Group** checked,
  that scope is the group's mapped categories. The dialog explicitly labels the
  fallback because colours/attributes can differ. Zero-stock matching products
  still count as matches and do not cause a fallback. Purchase eligibility,
  company boundaries and result limits remain enforced in both paths.
- Pins the original variant, even with zero/negative stock. Reads On Hand,
  Reserved, Free to Use, Incoming and Forecast through Odoo's stock ORM in a batch.
- Defaults to the RFQ final location or warehouse stock location; users may select
  another internal location in the same company. Quantities include child locations.
- Quantities use product stock UoM; an RFQ's purchasing UoM may be different.
- Incoming/Forecast are Odoo quantities, not promises that an overdue supplier
  will deliver. Similarity does not establish technical interchangeability.

## Installation / configuration

Install the addon after its declared dependencies. Purchase settings expose the
result limit (default 80 similar products, plus the original when necessary).
Only purchase users can open comparisons. Existing stock-quant read permissions
and company rules apply. This addon additionally grants purchase users read-only
colour-master access; no stock adjustment or colour editing permission is granted.

Services are Odoo AbstractModels and can be extended with `_inherit`. No upstream
addon files, external IDs or product data are changed.

## Validation

Run Odoo tests with `--test-enable --test-tags /purchase_variant_stock_compare`.
Tests cover colour/attribute mapping, unmapped fallbacks, exact UoM, zero/negative
stock, reservations, location boundaries and purchase/company permissions.
