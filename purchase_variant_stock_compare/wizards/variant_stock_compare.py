import logging

from odoo import _, api, Command, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class PurchaseVariantStockCompare(models.TransientModel):
    _name = 'purchase.variant.stock.compare'
    _description = 'Compare similar variants in receiving stock'
    _check_company_auto = True

    order_line_id = fields.Many2one('purchase.order.line', readonly=True, check_company=True)
    orderpoint_id = fields.Many2one('stock.warehouse.orderpoint', readonly=True, check_company=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True)
    product_id = fields.Many2one('product.product', required=True, readonly=True, check_company=True)
    location_id = fields.Many2one('stock.location', required=True, check_company=True,
                                 domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]")
    category_id = fields.Many2one('product.category', required=True)
    use_category_group = fields.Boolean(string='Use Category Group', default=False,
        help='Broaden comparison to the categories mapped in the selected group. Pack size and colour filters still apply.')
    category_group_id = fields.Many2one('modern.quotation.category.group', domain=[('active', '=', True)],
        help='Used only when Use Category Group is checked.')
    uom_id = fields.Many2one('uom.uom', required=True, string='Pack / stock UoM')
    colour_group_id = fields.Many2one('modern.quotation.colour.attribute.group',
                                     domain=[('active', '=', True)])
    match_description = fields.Char(readonly=True)
    truncated = fields.Boolean(readonly=True)
    line_ids = fields.One2many('purchase.variant.stock.compare.line', 'wizard_id', readonly=True)

    def _validate_scope(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('purchase.group_purchase_user'):
            raise AccessError(_('Only purchase users may compare RFQ stock.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('The comparison company is not allowed.'))
        self.product_id.check_access('read')
        self.location_id.check_access('read')
        if self.colour_group_id and not self.colour_group_id.active:
            raise UserError(_('Choose an active colour/attribute group.'))
        if self.use_category_group and (not self.category_group_id or not self.category_group_id.active):
            raise UserError(_('Choose an active category group or uncheck Use Category Group.'))
        if self.location_id.company_id != self.company_id or self.location_id.usage != 'internal':
            raise UserError(_('Choose an internal location in the comparison company.'))
        source = self.order_line_id or self.orderpoint_id
        if not source:
            raise UserError(_('Open comparison from an RFQ line or a reordering follow-up.'))
        source.check_access('read')
        if source.company_id != self.company_id or source.product_id != self.product_id:
            raise AccessError(_('The comparison must match its source product and company.'))

    @api.model
    def _open_for_line(self, line):
        location = line.location_final_id or line.order_id.picking_type_id.warehouse_id.lot_stock_id
        return self._open(line.product_id, line.company_id, location, {'order_line_id': line.id})

    @api.model
    def _open_for_orderpoint(self, orderpoint):
        return self._open(orderpoint.product_id, orderpoint.company_id, orderpoint.location_id,
                          {'orderpoint_id': orderpoint.id})

    @api.model
    def _open(self, product, company, location, source):
        values = self.env['purchase.variant.matching']._default_filters(product)
        wizard = self.create(dict(values, product_id=product.id, company_id=company.id,
                                  location_id=location.id, **source))
        return wizard.action_refresh()

    def action_refresh(self):
        self._validate_scope()
        _logger.debug('[RFQ_STOCK_COMPARE][REFRESH][START] wizard_id=%s user_id=%s', self.id, self.env.uid)
        matching = self.env['purchase.variant.matching']
        products, truncated, category_fallback = matching._find(self)
        # Always pin the original for a meaningful comparison, including zero/negative stock.
        products |= self.product_id
        rows = self.env['purchase.stock.comparison']._rows(self, products)
        self.write({
            'line_ids': [Command.clear()] + [Command.create(row) for row in rows],
            'truncated': truncated, 'match_description': matching._match_description(self, category_fallback),
        })
        _logger.debug('[RFQ_STOCK_COMPARE][REFRESH][END] wizard_id=%s rows=%s', self.id, len(rows))
        return {'type': 'ir.actions.act_window', 'name': _('Compare Similar Stock'),
                'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}


class PurchaseVariantStockCompareLine(models.TransientModel):
    _name = 'purchase.variant.stock.compare.line'
    _description = 'Variant stock comparison result'
    _order = 'is_original desc, free_qty desc, id'

    wizard_id = fields.Many2one('purchase.variant.stock.compare', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='wizard_id.company_id', store=True)
    product_id = fields.Many2one('product.product', required=True)
    category_id = fields.Many2one(related='product_id.categ_id')
    uom_id = fields.Many2one(related='product_id.uom_id')
    colour_code_id = fields.Many2one(related='product_id.colour_code_id')
    is_original = fields.Boolean()
    on_hand = fields.Float(digits='Product Unit of Measure')
    reserved = fields.Float(digits='Product Unit of Measure')
    free_qty = fields.Float(string='Free to Use', digits='Product Unit of Measure')
    incoming_qty = fields.Float(string='Incoming', digits='Product Unit of Measure')
    forecast_qty = fields.Float(string='Forecast', digits='Product Unit of Measure')

    def action_open_quants(self):
        self.ensure_one()
        self.check_access('read')
        self.wizard_id._validate_scope()
        return {'type': 'ir.actions.act_window', 'name': _('Stock by Location'),
                'res_model': 'stock.quant', 'view_mode': 'list,form',
                'domain': [('product_id', '=', self.product_id.id),
                           ('company_id', '=', self.company_id.id),
                           ('location_id', 'child_of', self.wizard_id.location_id.id)],
                'context': {'create': False, 'edit': False}}
