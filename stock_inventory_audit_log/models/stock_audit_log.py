import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class StockAuditLog(models.Model):
    _name = 'stock.audit.log'
    _description = 'Physical Inventory Audit Log'
    _order = 'timestamp_counted desc, id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name')
    quant_id = fields.Many2one('stock.quant', string='Quant', index=True, readonly=True, ondelete='set null')
    product_id = fields.Many2one('product.product', string='Product', required=True, index=True, readonly=True)
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        related='product_id.product_tmpl_id',
        store=True,
        index=True,
        readonly=True,
    )
    product_category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        related='product_id.categ_id',
        store=True,
        index=True,
        readonly=True,
    )
    product_default_code = fields.Char(
        string='Internal Reference',
        related='product_id.default_code',
        store=True,
        index=True,
        readonly=True,
    )
    product_type = fields.Selection(
        related='product_id.type',
        string='Product Type',
        store=True,
        index=True,
        readonly=True,
    )
    product_is_storable = fields.Boolean(
        string='Track Inventory',
        related='product_id.is_storable',
        store=True,
        index=True,
        readonly=True,
    )
    product_tracking = fields.Selection(
        related='product_id.tracking',
        string='Product Tracking',
        store=True,
        index=True,
        readonly=True,
    )
    product_sale_ok = fields.Boolean(
        string='Can Be Sold',
        related='product_id.sale_ok',
        store=True,
        index=True,
        readonly=True,
    )
    product_purchase_ok = fields.Boolean(
        string='Can Be Purchased',
        related='product_id.purchase_ok',
        store=True,
        index=True,
        readonly=True,
    )
    product_tag_ids = fields.Many2many(
        'product.tag',
        string='Product Tags',
        compute='_compute_product_tag_ids',
        search='_search_product_tag_ids',
        readonly=True,
    )
    product_available_in_pos = fields.Boolean(
        string='Available in POS',
        compute='_compute_product_available_in_pos',
        search='_search_product_available_in_pos',
        readonly=True,
    )
    barcode = fields.Char(string='Barcode', index=True, readonly=True)
    nexx_barcode = fields.Char(string='Nexx Barcode', index=True, readonly=True)
    location_id = fields.Many2one('stock.location', string='Location', required=True, index=True, readonly=True)
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number', index=True, readonly=True)
    package_id = fields.Many2one('stock.quant.package', string='Package', index=True, readonly=True)
    owner_id = fields.Many2one('res.partner', string='Owner', index=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True, readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', readonly=True)

    system_quant = fields.Float(string='System Quantity', digits='Product Unit of Measure', readonly=True)
    counted_quant = fields.Float(string='Counted Quantity', digits='Product Unit of Measure', readonly=True)
    difference = fields.Float(
        string='Difference',
        digits='Product Unit of Measure',
        compute='_compute_amounts',
        store=True,
        readonly=True,
    )

    unit_cost_excl_vat = fields.Monetary(string='Unit Cost Excl. VAT', readonly=True)
    vat_amount_per_unit = fields.Monetary(string='VAT Per Unit', readonly=True)
    unit_cost_incl_vat = fields.Monetary(
        string='Unit Cost Incl. VAT',
        compute='_compute_amounts',
        store=True,
        readonly=True,
    )
    value_difference_excl_vat = fields.Monetary(
        string='Value Difference Excl. VAT',
        compute='_compute_amounts',
        store=True,
        readonly=True,
    )
    value_difference_vat = fields.Monetary(
        string='VAT Difference',
        compute='_compute_amounts',
        store=True,
        readonly=True,
    )
    value_difference_incl_vat = fields.Monetary(
        string='Value Difference Incl. VAT',
        compute='_compute_amounts',
        store=True,
        readonly=True,
    )

    timestamp_counted = fields.Datetime(string='Counted At', required=True, default=fields.Datetime.now, readonly=True)
    timestamp_applied = fields.Datetime(string='Applied At', readonly=True)
    employee_counted_id = fields.Many2one('res.users', string='Counted By', required=True, readonly=True)
    employee_applied_id = fields.Many2one('res.users', string='Applied By', readonly=True)
    state = fields.Selection(
        [('draft', 'Counted / Pending'), ('applied', 'Applied / Done')],
        string='Status',
        required=True,
        default='draft',
        index=True,
        readonly=True,
    )
    source = fields.Selection(
        [
            ('manual_inventory', 'Manual Inventory'),
            ('barcode_inventory', 'Barcode Inventory'),
            ('auto_apply', 'Auto Apply'),
            ('import', 'Import'),
            ('unknown', 'Unknown'),
        ],
        string='Source',
        default='unknown',
        index=True,
        readonly=True,
    )
    debug_reference = fields.Char(string='Debug Reference', readonly=True)

    @api.depends('product_id', 'location_id', 'difference', 'state')
    def _compute_display_name(self):
        for log in self:
            parts = [log.product_id.display_name or _('Inventory Audit')]
            if log.location_id:
                parts.append(log.location_id.display_name)
            parts.append('%s %s' % (log.difference, log.product_uom_id.name or ''))
            log.display_name = ' - '.join(parts)

    @api.depends('system_quant', 'counted_quant', 'unit_cost_excl_vat', 'vat_amount_per_unit')
    def _compute_amounts(self):
        for log in self:
            log.difference = log.counted_quant - log.system_quant
            log.unit_cost_incl_vat = log.unit_cost_excl_vat + log.vat_amount_per_unit
            log.value_difference_excl_vat = log.difference * log.unit_cost_excl_vat
            log.value_difference_vat = log.difference * log.vat_amount_per_unit
            log.value_difference_incl_vat = log.difference * log.unit_cost_incl_vat

    @api.depends('product_id')
    def _compute_product_tag_ids(self):
        for log in self:
            if 'all_product_tag_ids' in log.product_id._fields:
                log.product_tag_ids = log.product_id.all_product_tag_ids
            else:
                log.product_tag_ids = log.product_id.product_tag_ids

    def _search_product_tag_ids(self, operator, value):
        product_model = self.env['product.product']
        if 'all_product_tag_ids' in product_model._fields:
            return [('product_id.all_product_tag_ids', operator, value)]
        return [('product_id.product_tag_ids', operator, value)]

    @api.depends('product_id')
    def _compute_product_available_in_pos(self):
        for log in self:
            log.product_available_in_pos = (
                'available_in_pos' in log.product_id._fields
                and bool(log.product_id.available_in_pos)
            )

    def _search_product_available_in_pos(self, operator, value):
        if 'available_in_pos' not in self.env['product.product']._fields:
            if (operator == '=' and value) or (operator == '!=' and not value):
                return [('id', '=', 0)]
            return []
        return [('product_id.available_in_pos', operator, value)]

    def _check_internal_write_allowed(self):
        if not self.env.context.get('stock_audit_internal'):
            _logger.warning(
                "AUDIT_MANUAL_WRITE_BLOCKED model=stock.audit.log user_id=%s ids=%s",
                self.env.uid,
                self.ids,
            )
            raise AccessError(_('Inventory audit logs are read-only.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('stock_audit_internal'):
            _logger.warning("AUDIT_MANUAL_CREATE_BLOCKED model=stock.audit.log user_id=%s", self.env.uid)
            raise AccessError(_('Inventory audit logs are read-only.'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_internal_write_allowed()
        return super().write(vals)

    def unlink(self):
        self._check_internal_write_allowed()
        return super().unlink()
