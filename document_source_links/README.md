# Document Source Links (Odoo 18)

Reusable source navigation for any model and form. No business-app dependency,
generic writable link table, elevated privileges, or guessed order-name searches.

## Installation

Install `document_source_links_purchase`, `document_source_links_pos`, and
`document_source_links_pending` for the requested receipt, POS delivery and pending
collection transfers. Their dependencies install the framework and Inventory
bridge. Install `document_source_links_sale` for sales-order transfers.
Modules are deliberately not automatically installed into existing databases.

The pending-collection dependency's manifest loads its security groups before
the access CSV, and its action before menus, so fresh installation is supported.
No existing business workflow implementation was modified.

The Inventory form displays Linked Sources below the existing Source Document.
The original origin field and manufacturing behavior remain unchanged. Sources
open in read mode; normal Odoo access rights still govern editing the target.

## Extend to another model

In an addon depending on this framework and the target application:

```python
class Invoice(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'document.source.link.mixin']

    def _get_source_link_records(self):
        sources = super()._get_source_link_records()
        role = self.env._('Source Order')
        sources.extend((role, order) for order in self.my_order_ids)
        return sources

    @api.depends('my_order_ids')
    def _compute_source_link_data(self):
        return super()._compute_source_link_data()
```

Inherit the relevant form and insert:

```xml
<field name="source_link_data" widget="document_source_links" readonly="1"/>
```

Provider contract: return `(translated role, singleton record)` tuples; call
`super()`; discover sources only from trusted server-side relationships; check
access before reading intermediate records. Never use `sudo()`. No source writes
belong in discovery. The framework filters inaccessible/missing targets, company
mismatches, duplicates, and self-links before returning labels or IDs. The public
open action checks parent access and recomputes the permitted sources on every
click. Submitted model/ID pairs cannot open arbitrary records.

## Inventory bridges

- Inventory: returns, backorders, upstream stock move chains; cycle protection.
- Purchase: all purchase orders on source moves, including merged transfers.
- POS: native POS order relations; never searches for orders by reference text.
- Sales: sale order and sale-line relations.
- Pending: stores a separate, company-checked collection relation during the
  original holding, collection and cancellation workflows using inheritance.
  Does not populate native `pos_order_id` or alter valuation/stock operations.

Existing pending transfers are resolved without database writes: first through
collection-line stock moves, then unique same-company exact legacy origin
formats from the original addon. Ambiguous/malformed origins remain unlinked.
Legacy origin matching is compatibility evidence, not a new persistent relation;
manually fabricated matching origins should be reviewed as part of data cleanup.
No bulk backfill, cron, source-data migration, or ACL expansion is performed.

Computed links are nonstored and user-specific. An open form must be reloaded
after upstream source relationships or permissions change. Click authorization
always uses current access, regardless of the displayed cached links.

Enable DEBUG for `odoo.addons.document_source_links` and
`odoo.addons.document_source_links_pending` to see operation boundaries. Logs
contain IDs and counts, never document contents, credentials, or customer data.
