# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class PaintTintingMistake(models.Model):
    _name = 'paint.tinting.mistake'
    _description = 'Mistaken Tinted Product Mapping'
    _order = 'mistake_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', required=True, copy=False, default='New', index=True)
    active = fields.Boolean(default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('under_review', 'Under Review'),
        ('confirmed', 'Confirmed Mistake'),
        ('quarantined', 'Stock Quarantined'),
        ('resolved', 'Resolution Decided'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, index=True)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    mistake_date = fields.Datetime(
        string='Mistake Date',
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    discovered_date = fields.Datetime(
        string='Discovered Date',
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    days_hidden = fields.Float(string='Days Hidden', compute='_compute_days_hidden', store=True)
    detection_source = fields.Selection([
        ('declared_by_employee', 'Declared by Employee'),
        ('stock_count', 'Found During Stock Count'),
        ('customer_return', 'Customer Return'),
        ('supervisor_audit', 'Supervisor Audit'),
        ('other', 'Other'),
    ], string='Detection Source', required=True, default='declared_by_employee', index=True)
    reported_on_time = fields.Boolean(string='Reported On Time')
    concealment_suspected = fields.Boolean(string='Concealment Suspected')

    actual_product_id = fields.Many2one(
        'product.product',
        string='Mistaken Tinted Product',
        required=True,
        domain="[('product_tmpl_id.is_tinted_product', '=', True)]",
        index=True,
        check_company=True,
    )
    actual_lot_id = fields.Many2one(
        'stock.lot',
        string='Lot/Serial Number',
        domain="[('product_id', '=', actual_product_id)]",
        index=True,
        check_company=True,
    )
    actual_qty = fields.Float(string='Quantity', required=True, default=1.0)
    actual_uom_id = fields.Many2one('uom.uom', string='Actual UoM', required=True)
    location_id = fields.Many2one('stock.location', string='Shelf/Location', domain="[('usage', '=', 'internal')]")
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')

    actual_bom_id = fields.Many2one('mrp.bom', string='Actual Tinting BOM', compute='_compute_actual_traceability', store=True)
    actual_mo_id = fields.Many2one('mrp.production', string='Actual MO', compute='_compute_actual_traceability', store=True)
    actual_base_product_id = fields.Many2one('product.product', string='Actual Base Product', compute='_compute_actual_traceability', store=True)
    actual_base_category_id = fields.Many2one('product.category', string='Actual Base Category', compute='_compute_actual_traceability', store=True)
    actual_colour_code_id = fields.Many2one('colour.code', string='Actual Colour Code', compute='_compute_actual_traceability', store=True)
    actual_fandeck_id = fields.Many2one('colour.fandeck', string='Actual Fandeck', compute='_compute_actual_traceability', store=True)

    intended_product_id = fields.Many2one(
        'product.product',
        string='Intended Tinted Product',
        domain="[('product_tmpl_id.is_tinted_product', '=', True)]",
        check_company=True,
    )
    intended_base_product_id = fields.Many2one('product.product', string='Intended Base Product', check_company=True)
    intended_base_category_id = fields.Many2one('product.category', string='Intended Base Category')
    intended_uom_id = fields.Many2one('uom.uom', string='Intended UoM')
    intended_colour_code_id = fields.Many2one('colour.code', string='Intended Colour Code')
    intended_fandeck_id = fields.Many2one('colour.fandeck', string='Intended Fandeck')
    sale_order_id = fields.Many2one('sale.order', string='Related Sale Order', check_company=True)
    sale_order_line_id = fields.Many2one('sale.order.line', string='Related Sale Order Line')
    pos_order_id = fields.Many2one('pos.order', string='Related POS Order')

    mismatch_type = fields.Selection([
        ('wrong_uom', 'Wrong Pack/UoM'),
        ('wrong_base', 'Wrong Base Product'),
        ('wrong_category', 'Wrong Category'),
        ('wrong_colour', 'Wrong Colour'),
        ('wrong_fandeck', 'Wrong Fandeck'),
        ('wrong_customer', 'Wrong Customer/Order'),
        ('duplicate_unwanted', 'Duplicate/Unwanted Tint'),
        ('unknown', 'Unknown'),
    ], string='Mismatch Type', compute='_compute_mismatch_type', store=True, index=True)

    employee_line_ids = fields.One2many(
        'paint.tinting.mistake.employee.line',
        'mistake_id',
        string='Responsible Employees',
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        compute='_compute_employee_ids',
        store=True,
    )
    reported_by_employee_id = fields.Many2one('hr.employee', string='Reported By')
    reviewed_by_id = fields.Many2one('res.users', string='Reviewed By', readonly=True)
    reviewed_date = fields.Datetime(string='Reviewed Date', readonly=True)

    amount_source = fields.Selection([
        ('exclusive', 'Stored Costs Exclude VAT'),
        ('inclusive', 'Stored Costs Include VAT'),
    ], string='Cost Source', default='exclusive', required=True)
    vat_percent = fields.Float(
        string='VAT %',
        default=lambda self: self.env['paint.tinting.cost.policy']._get_default_vat_percent(),
    )
    wrong_base_cost_excl_vat = fields.Monetary(string='Base Cost Excl. VAT', currency_field='currency_id', compute='_compute_cost_amounts', store=True)
    wrong_base_cost_incl_vat = fields.Monetary(string='Base Cost Incl. VAT', currency_field='currency_id', compute='_compute_cost_amounts', store=True)
    wrong_colorant_cost_excl_vat = fields.Monetary(string='Colorants Cost Excl. VAT', currency_field='currency_id', compute='_compute_cost_amounts', store=True)
    wrong_colorant_cost_incl_vat = fields.Monetary(string='Colorants Cost Incl. VAT', currency_field='currency_id', compute='_compute_cost_amounts', store=True)
    total_cost_excl_vat = fields.Monetary(string='Total Cost Excl. VAT', currency_field='currency_id', compute='_compute_cost_amounts', store=True)
    total_cost_incl_vat = fields.Monetary(string='Total Cost Incl. VAT', currency_field='currency_id', compute='_compute_cost_amounts', store=True, group_operator='sum')
    expected_recoverable_value = fields.Monetary(string='Expected Recoverable Value', currency_field='currency_id')
    estimated_loss_amount = fields.Monetary(string='Estimated Loss', currency_field='currency_id', compute='_compute_loss_amounts', store=True, group_operator='sum')
    recommended_recovery_amount = fields.Monetary(string='Recommended Recovery', currency_field='currency_id', compute='_compute_loss_amounts', store=True)
    final_recovery_amount = fields.Monetary(string='Final Recovery', currency_field='currency_id')

    financial_decision = fields.Selection([
        ('pending', 'Pending Decision'),
        ('company_absorb', 'Company Absorbs'),
        ('employee_recovery', 'Employee Recovery'),
        ('shared', 'Shared Recovery'),
        ('forgiven', 'Forgiven'),
    ], string='Financial Decision', default='pending', required=True, index=True)
    stock_decision = fields.Selection([
        ('quarantine', 'Quarantine'),
        ('keep_for_resale', 'Keep for Resale'),
        ('discount_sale', 'Discount Sale'),
        ('internal_use', 'Internal Use'),
        ('scrap', 'Scrap/Write Off'),
        ('other', 'Other'),
    ], string='Stock Decision', default='quarantine', required=True, index=True)
    notes = fields.Text(string='Notes')
    resolution_notes = fields.Text(string='Resolution Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('paint.tinting.mistake') or 'New'
        records = super().create(vals_list)
        records._log_tagged('create', 'Mistake mapping created')
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals:
            self._log_tagged('write', 'Mistake mapping updated', fields=','.join(sorted(vals)))
        return res

    def _log_tagged(self, tag, message, **extra):
        for record in self:
            payload = ' '.join('%s=%s' % (key, value) for key, value in sorted(extra.items()))
            _logger.info(
                '[PAINT_TINTING][MISTAKE][%s] ref=%s id=%s product_id=%s lot_id=%s state=%s %s | %s',
                tag.upper(),
                record.name,
                record.id,
                record.actual_product_id.id if record.actual_product_id else False,
                record.actual_lot_id.id if record.actual_lot_id else False,
                record.state,
                payload,
                message,
            )

    @api.onchange('actual_product_id')
    def _onchange_actual_product_id(self):
        for record in self:
            if record.actual_product_id:
                record.actual_uom_id = record.actual_product_id.uom_id
                tmpl = record.actual_product_id.product_tmpl_id
                record.actual_colour_code_id = tmpl.colour_code_id
                record.actual_fandeck_id = tmpl.fandeck_id

    @api.onchange('intended_product_id')
    def _onchange_intended_product_id(self):
        for record in self:
            product = record.intended_product_id
            if product:
                record.intended_uom_id = product.uom_id
                record.intended_colour_code_id = product.product_tmpl_id.colour_code_id
                record.intended_fandeck_id = product.product_tmpl_id.fandeck_id
                bom = record._find_tinting_bom(product)
                if bom:
                    record.intended_base_product_id = bom.base_variant_id
                    record.intended_base_category_id = bom.base_variant_id.categ_id

    @api.depends('mistake_date', 'discovered_date')
    def _compute_days_hidden(self):
        for record in self:
            if record.mistake_date and record.discovered_date:
                delta = record.discovered_date - record.mistake_date
                record.days_hidden = max(delta.total_seconds() / 86400.0, 0.0)
            else:
                record.days_hidden = 0.0

    @api.depends('employee_line_ids.employee_id')
    def _compute_employee_ids(self):
        for record in self:
            record.employee_ids = [(6, 0, record.employee_line_ids.employee_id.ids)]

    @api.depends('actual_product_id', 'actual_lot_id')
    def _compute_actual_traceability(self):
        for record in self:
            mo = record._find_actual_mo()
            bom = mo.bom_id if mo else record._find_tinting_bom(record.actual_product_id)
            base_product = bom.base_variant_id if bom else False
            tmpl = record.actual_product_id.product_tmpl_id if record.actual_product_id else False
            record.actual_mo_id = mo
            record.actual_bom_id = bom
            record.actual_base_product_id = base_product
            record.actual_base_category_id = base_product.categ_id if base_product else False
            record.actual_colour_code_id = (
                (bom.colour_code_id if bom else False)
                or (tmpl.colour_code_id if tmpl else False)
            )
            record.actual_fandeck_id = (
                (bom.fandeck_id if bom else False)
                or (tmpl.fandeck_id if tmpl else False)
            )

    @api.depends(
        'actual_uom_id', 'actual_base_product_id', 'actual_base_category_id',
        'actual_colour_code_id', 'actual_fandeck_id', 'intended_uom_id',
        'intended_base_product_id', 'intended_base_category_id',
        'intended_colour_code_id', 'intended_fandeck_id',
    )
    def _compute_mismatch_type(self):
        for record in self:
            if record.intended_colour_code_id and record.actual_colour_code_id != record.intended_colour_code_id:
                record.mismatch_type = 'wrong_colour'
            elif record.intended_fandeck_id and record.actual_fandeck_id != record.intended_fandeck_id:
                record.mismatch_type = 'wrong_fandeck'
            elif record.intended_base_product_id and record.actual_base_product_id != record.intended_base_product_id:
                record.mismatch_type = 'wrong_base'
            elif record.intended_base_category_id and record.actual_base_category_id != record.intended_base_category_id:
                record.mismatch_type = 'wrong_category'
            elif record.intended_uom_id and record.actual_uom_id != record.intended_uom_id:
                record.mismatch_type = 'wrong_uom'
            else:
                record.mismatch_type = 'unknown'

    @api.depends(
        'actual_product_id', 'actual_qty', 'actual_uom_id', 'actual_bom_id',
        'actual_base_product_id', 'amount_source', 'vat_percent',
    )
    def _compute_cost_amounts(self):
        policy = self.env['paint.tinting.cost.policy']
        for record in self:
            inclusive_source = record.amount_source == 'inclusive'
            base = policy.product_cost_amounts(
                record.actual_base_product_id or record.actual_product_id,
                quantity=record.actual_qty,
                uom=record.actual_uom_id,
                amount_is_vat_inclusive=inclusive_source,
                vat_percent=record.vat_percent,
            )
            colorant_excl = 0.0
            if record.actual_bom_id:
                for line in record.actual_bom_id.bom_line_ids.filtered('is_colorant_line'):
                    colorant_excl += (line.unit_cost_excl_vat or line.product_id.standard_price or 0.0) * (line.product_qty or 0.0)
            colorant = policy.normalize_amounts(
                colorant_excl * (record.actual_qty or 0.0),
                amount_is_vat_inclusive=inclusive_source,
                vat_percent=record.vat_percent,
            )
            record.wrong_base_cost_excl_vat = base['excl']
            record.wrong_base_cost_incl_vat = base['incl']
            record.wrong_colorant_cost_excl_vat = colorant['excl']
            record.wrong_colorant_cost_incl_vat = colorant['incl']
            record.total_cost_excl_vat = base['excl'] + colorant['excl']
            record.total_cost_incl_vat = base['incl'] + colorant['incl']

    @api.depends('total_cost_incl_vat', 'expected_recoverable_value', 'financial_decision')
    def _compute_loss_amounts(self):
        for record in self:
            loss = max((record.total_cost_incl_vat or 0.0) - (record.expected_recoverable_value or 0.0), 0.0)
            record.estimated_loss_amount = loss
            record.recommended_recovery_amount = 0.0 if record.financial_decision in ('company_absorb', 'forgiven') else loss

    @api.constrains('actual_qty')
    def _check_actual_qty(self):
        for record in self:
            rounding = record.actual_uom_id.rounding if record.actual_uom_id else 0.01
            if float_compare(record.actual_qty, 0.0, precision_rounding=rounding) <= 0:
                raise ValidationError(_('Quantity must be greater than zero.'))

    def _find_tinting_bom(self, product):
        if not product:
            return self.env['mrp.bom']
        return self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('is_tinting_bom', '=', True),
        ], order='id desc', limit=1)

    def _find_actual_mo(self):
        self.ensure_one()
        domain = [
            ('product_id', '=', self.actual_product_id.id),
            ('is_tinting_mo', '=', True),
        ]
        if self.actual_lot_id:
            domain.append(('lot_producing_id', '=', self.actual_lot_id.id))
        return self.env['mrp.production'].search(domain, order='id desc', limit=1)

    def action_submit_review(self):
        self.write({'state': 'under_review'})

    def action_confirm_mistake(self):
        self.write({
            'state': 'confirmed',
            'reviewed_by_id': self.env.user.id,
            'reviewed_date': fields.Datetime.now(),
        })
        self._log_tagged('confirm', 'Mistake confirmed by reviewer')

    def action_quarantine(self):
        self.write({'state': 'quarantined', 'stock_decision': 'quarantine'})
        self._log_tagged('quarantine', 'Mistaken stock marked for quarantine')

    def action_resolve(self):
        for record in self:
            if record.financial_decision == 'pending':
                raise UserError(_('Select a financial decision before resolving.'))
        self.write({'state': 'resolved'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_open_spreadsheet_source(self):
        return self.env.ref('paint_tinting.action_tinted_mistake_spreadsheet_source').read()[0]
