# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup, escape


_logger = logging.getLogger(__name__)


class SaleOrderLineTintEditWizardLine(models.TransientModel):
    _name = 'sale.order.line.tint.edit.wizard.line'
    _description = 'Sale Order Line Tint Edit Wizard Line'
    _order = 'colorant_code, id'

    wizard_id = fields.Many2one(
        'sale.order.line.tint.edit.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    colorant_id = fields.Many2one(
        'product.product',
        string='Colorant',
        required=True,
        domain="[('product_tmpl_id.is_colorant', '=', True)]",
    )
    colorant_code = fields.Char(string='Code', compute='_compute_colorant_code', store=True, readonly=True)
    shots = fields.Float(string='Total Shots', digits=(10, 2), required=True)
    shots_to_add = fields.Float(string='Add Shots', digits=(10, 2))
    shots_history = fields.Char(
        string='Shots History',
        default='',
        help='Shows each shots addition step, e.g. 30 + 15 + 5 = 50',
    )
    shots_history_total = fields.Float(
        string='Shots History Total',
        digits=(10, 2),
        default=0.0,
        help='Internal guard used to keep shot history when Total Shots is updated by Add Shots.',
    )
    unit_cost_excl_vat = fields.Float(
        string='Unit Cost Excl. VAT',
        related='colorant_id.standard_price',
        readonly=True,
        digits='Product Price',
    )
    qty_litres = fields.Float(string='Quantity (L)', compute='_compute_amounts', digits=(10, 6))
    line_cost_incl_vat = fields.Float(string='Cost Incl. VAT', compute='_compute_amounts', digits='Product Price')

    @api.depends('colorant_id')
    def _compute_colorant_code(self):
        for line in self:
            line.colorant_code = line.colorant_id.product_tmpl_id.colorant_code or ''

    @api.depends('shots', 'unit_cost_excl_vat')
    def _compute_amounts(self):
        policy = self.env['paint.tinting.cost.policy']
        vat_factor = policy._get_vat_factor()
        for line in self:
            line.qty_litres = ((line.shots or 0.0) * 0.616) / 1000.0
            line.line_cost_incl_vat = (line.unit_cost_excl_vat or 0.0) * line.qty_litres * vat_factor

    @api.onchange('shots_to_add')
    def _onchange_shots_to_add(self):
        for line in self:
            if line.shots_to_add and line.shots_to_add > 0:
                increment = line.shots_to_add
                line.shots = (line.shots or 0.0) + increment
                line.shots_history_total = line.shots
                line.shots_to_add = 0.0
                step = "%g" % increment
                line.shots_history = (
                    "%s + %s" % (line.shots_history, step)
                    if line.shots_history else step
                )

    @api.onchange('shots')
    def _onchange_shots(self):
        for line in self:
            if line.shots_history and line.shots == line.shots_history_total:
                continue
            line.shots_history = ''
            line.shots_history_total = 0.0


class SaleOrderLineTintEditWizard(models.TransientModel):
    _name = 'sale.order.line.tint.edit.wizard'
    _description = 'Edit Sale Order Line Tint Colourants'

    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        required=True,
        readonly=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        related='sale_order_line_id.order_id',
        readonly=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Quoted Product',
        related='sale_order_line_id.product_id',
        readonly=True,
    )
    colour_code_id = fields.Many2one(
        'colour.code',
        string='Colour Code',
        related='sale_order_line_id.colour_code_id',
        readonly=True,
    )
    fandeck_id = fields.Many2one(
        'colour.fandeck',
        string='Fandeck',
        related='sale_order_line_id.fandeck_id',
        readonly=True,
    )
    base_category_id = fields.Many2one(
        'product.category',
        string='Base Category',
        related='sale_order_line_id.base_category_id',
        readonly=True,
    )
    base_product_id = fields.Many2one(
        'product.product',
        string='Base Product',
        related='sale_order_line_id.base_product_id',
        readonly=True,
    )
    base_product_uom_id = fields.Many2one(
        'uom.uom',
        string='Base UOM',
        related='sale_order_line_id.base_product_uom_id',
        readonly=True,
    )
    before_formula_json = fields.Text(string='Before Formula JSON', readonly=True)
    before_base_cost_incl_vat = fields.Float(string='Before Base Cost Incl. VAT', digits='Product Price', readonly=True)
    before_colorant_cost_incl_vat = fields.Float(string='Before Colorant Cost Incl. VAT', digits='Product Price', readonly=True)
    before_total_cost_incl_vat = fields.Float(string='Before Total Cost Incl. VAT', digits='Product Price', readonly=True)
    before_price_unit = fields.Float(string='Before Selling Price', digits='Product Price', readonly=True)

    line_ids = fields.One2many(
        'sale.order.line.tint.edit.wizard.line',
        'wizard_id',
        string='Colourants',
    )
    new_colorant_id = fields.Many2one(
        'product.product',
        string='New Colourant',
        domain="[('product_tmpl_id.is_colorant', '=', True)]",
    )
    new_colorant_shots = fields.Float(string='New Shots', digits=(10, 2))
    change_reason = fields.Text(string='Change Reason')

    after_colorant_cost_incl_vat = fields.Float(
        string='New Colorant Cost Incl. VAT',
        compute='_compute_after_costs',
        digits='Product Price',
    )
    after_total_cost_incl_vat = fields.Float(
        string='New Total Cost Incl. VAT',
        compute='_compute_after_costs',
        digits='Product Price',
    )
    cost_delta_incl_vat = fields.Float(
        string='Cost Change Incl. VAT',
        compute='_compute_after_costs',
        digits='Product Price',
    )
    profit_after_incl_vat = fields.Float(
        string='Profit After Incl. VAT',
        compute='_compute_after_costs',
        digits='Product Price',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line = self._get_active_sale_line()
        if not line:
            return res

        self._validate_editable_line(line)
        formula = self._parse_formula(line.tinting_formula_json)
        colorants_by_code = self._get_mapped_colorants_by_code()
        commands = []
        for code in self._get_colorant_code_sequence(colorants_by_code):
            colorant = colorants_by_code.get(code)
            data = formula.get(code, {})
            commands.append((0, 0, {
                'colorant_id': colorant.id,
                'shots': data.get('shots') or 0.0,
            }))

        missing_codes = sorted(set(formula) - set(colorants_by_code))
        if missing_codes:
            _logger.warning(
                "[PAINT_TINTING][SO_LINE_TINT_EDIT][ERROR] "
                "line_id=%s missing_mapped_colorant_codes=%s",
                line.id, missing_codes,
            )

        res.update({
            'sale_order_line_id': line.id,
            'before_formula_json': line.tinting_formula_json or '{}',
            'before_base_cost_incl_vat': line.quoted_base_cost,
            'before_colorant_cost_incl_vat': line.quoted_colorant_cost,
            'before_total_cost_incl_vat': line.quoted_cost_at_creation,
            'before_price_unit': line.price_unit,
            'line_ids': commands,
        })
        return res

    @api.depends('line_ids.shots', 'line_ids.colorant_id', 'before_base_cost_incl_vat', 'before_total_cost_incl_vat', 'before_price_unit')
    def _compute_after_costs(self):
        for wizard in self:
            colorant_cost = sum(wizard.line_ids.mapped('line_cost_incl_vat'))
            total_cost = (wizard.before_base_cost_incl_vat or 0.0) + colorant_cost
            wizard.after_colorant_cost_incl_vat = colorant_cost
            wizard.after_total_cost_incl_vat = total_cost
            wizard.cost_delta_incl_vat = total_cost - (wizard.before_total_cost_incl_vat or 0.0)
            wizard.profit_after_incl_vat = (wizard.before_price_unit or 0.0) - total_cost

    def action_add_colorant(self):
        self.ensure_one()
        if not self.new_colorant_id:
            raise UserError(_("Please select a colourant to add."))
        if self.new_colorant_shots <= 0:
            raise UserError(_("Please enter shots greater than zero."))

        existing = self.line_ids.filtered(lambda item: item.colorant_id == self.new_colorant_id)
        if existing:
            existing[0].shots += self.new_colorant_shots
        else:
            self.write({
                'line_ids': [(0, 0, {
                    'colorant_id': self.new_colorant_id.id,
                    'shots': self.new_colorant_shots,
                })]
            })
        self.new_colorant_id = False
        self.new_colorant_shots = 0.0
        return self._reopen()

    def action_apply_changes(self):
        self.ensure_one()
        try:
            return self._action_apply_changes_impl()
        except Exception as error:
            line = self.sale_order_line_id
            _logger.exception(
                "[PAINT_TINTING][SO_LINE_TINT_EDIT][ERROR] sale_order_id=%s "
                "line_id=%s error=%s",
                line.order_id.id if line else False,
                line.id if line else False,
                error,
            )
            raise

    def _action_apply_changes_impl(self):
        self.ensure_one()
        line = self.sale_order_line_id.exists()
        self._validate_editable_line(line)

        _logger.info(
            "[PAINT_TINTING][SO_LINE_TINT_EDIT][START] sale_order_id=%s "
            "line_id=%s user_id=%s",
            line.order_id.id, line.id, self.env.user.id,
        )

        before_snapshot = self._snapshot_line(line)
        formula = self._build_formula_payload()
        if not formula:
            raise ValidationError(_("At least one colourant with positive shots is required."))

        after_formula_json = json.dumps(formula, sort_keys=True)
        after_colorant_cost = self.after_colorant_cost_incl_vat
        after_total_cost = self.after_total_cost_incl_vat
        policy = self.env['paint.tinting.cost.policy']
        purchase_price = policy.normalize_amounts(
            after_total_cost,
            amount_is_vat_inclusive=True,
        )['excl']

        revision_no = self.env['paint.tinting.sale.line.revision'].search_count([
            ('sale_order_line_id', '=', line.id),
        ]) + 1
        metadata = {
            'before': before_snapshot,
            'after': {
                'formula': formula,
                'quoted_base_cost': line.quoted_base_cost,
                'quoted_colorant_cost': after_colorant_cost,
                'quoted_cost_at_creation': after_total_cost,
                'price_unit': line.price_unit,
                'colour_code_id': line.colour_code_id.id,
                'fandeck_id': line.fandeck_id.id,
                'base_category_id': line.base_category_id.id,
                'base_product_id': line.base_product_id.id,
                'base_product_uom_id': line.base_product_uom_id.id,
            },
        }

        self.env['paint.tinting.sale.line.revision'].create({
            'name': '%s / line %s / rev %s' % (line.order_id.name, line.id, revision_no),
            'sale_order_id': line.order_id.id,
            'sale_order_line_id': line.id,
            'revision_no': revision_no,
            'edited_by_id': self.env.user.id,
            'change_reason': self.change_reason,
            'before_formula_json': line.tinting_formula_json or '{}',
            'after_formula_json': after_formula_json,
            'metadata_json': json.dumps(metadata, sort_keys=True),
            'before_colour_code_id': line.colour_code_id.id,
            'after_colour_code_id': line.colour_code_id.id,
            'before_fandeck_id': line.fandeck_id.id,
            'after_fandeck_id': line.fandeck_id.id,
            'before_base_category_id': line.base_category_id.id,
            'after_base_category_id': line.base_category_id.id,
            'before_base_product_id': line.base_product_id.id,
            'after_base_product_id': line.base_product_id.id,
            'before_base_product_uom_id': line.base_product_uom_id.id,
            'after_base_product_uom_id': line.base_product_uom_id.id,
            'before_base_cost_incl_vat': line.quoted_base_cost,
            'after_base_cost_incl_vat': line.quoted_base_cost,
            'before_colorant_cost_incl_vat': line.quoted_colorant_cost,
            'after_colorant_cost_incl_vat': after_colorant_cost,
            'before_total_cost_incl_vat': line.quoted_cost_at_creation,
            'after_total_cost_incl_vat': after_total_cost,
            'before_price_unit': line.price_unit,
            'after_price_unit': line.price_unit,
        })

        vals = {
            'tinting_formula_json': after_formula_json,
            'quoted_colorant_cost': after_colorant_cost,
            'quoted_cost_at_creation': after_total_cost,
        }
        if 'purchase_price' in line._fields:
            vals['purchase_price'] = purchase_price
        line.write(vals)

        line.order_id.message_post(
            body=Markup(
                "<div>"
                "<p><strong>Tint recipe updated</strong></p>"
                "<p>The colourant shots were revised before manufacturing. "
                "A full before-and-after snapshot was saved to Tint History.</p>"
                "<table class='table table-sm o_main_table' style='width:auto;'>"
                "<tbody>"
                "<tr><td><strong>Line</strong></td><td>%s</td></tr>"
                "<tr><td><strong>Revision</strong></td><td>%s</td></tr>"
                "<tr><td><strong>Colourant cost</strong></td><td>%.2f KES -> %.2f KES</td></tr>"
                "<tr><td><strong>Total cost</strong></td><td>%.2f KES -> %.2f KES</td></tr>"
                "<tr><td><strong>Reason</strong></td><td>%s</td></tr>"
                "</tbody>"
                "</table>"
                "</div>"
            ) % (
                escape(line.product_id.display_name),
                revision_no,
                before_snapshot['quoted_colorant_cost'],
                after_colorant_cost,
                before_snapshot['quoted_cost_at_creation'],
                after_total_cost,
                escape(self.change_reason or _('Not provided')),
            ),
            subject=_("Tint recipe updated"),
        )

        _logger.info(
            "[PAINT_TINTING][SO_LINE_TINT_EDIT][END] sale_order_id=%s "
            "line_id=%s revision_no=%s before_total=%.4f after_total=%.4f",
            line.order_id.id, line.id, revision_no,
            before_snapshot['quoted_cost_at_creation'], after_total_cost,
        )

        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def _get_active_sale_line(self):
        if self.env.context.get('active_model') != 'sale.order.line':
            return self.env['sale.order.line']
        return self.env['sale.order.line'].browse(self.env.context.get('active_id')).exists()

    @api.model
    def _validate_editable_line(self, line):
        if not line:
            raise UserError(_("No sale order line was selected."))
        if not line.is_tinted_product_line:
            raise UserError(_("This sale order line is not a tinted product line."))
        if line.tinted_product_created:
            raise UserError(_("This tinted line already has a tinted product/MO. Use a correction workflow instead."))
        if line.order_id.state not in ('draft', 'sent'):
            raise UserError(_("Tint colourants can only be edited while the quotation is draft or sent."))

    @api.model
    def _parse_formula(self, formula_json):
        try:
            payload = json.loads(formula_json or '{}')
        except (TypeError, ValueError) as error:
            raise UserError(_("Invalid tinting formula JSON on the sale order line: %s") % error)
        if not isinstance(payload, dict):
            raise UserError(_("Tinting formula must be a JSON object."))
        return payload

    @api.model
    def _find_colorant(self, code):
        return self.env['product.product'].search([
            ('product_tmpl_id.is_colorant', '=', True),
            ('product_tmpl_id.colorant_code', '=ilike', code),
        ], limit=1)

    @api.model
    def _get_mapped_colorants_by_code(self):
        colorants = self.env['product.product'].search([
            ('product_tmpl_id.is_colorant', '=', True),
            ('product_tmpl_id.colorant_code', '!=', False),
        ])
        mapped = {}
        for colorant in colorants:
            code = (colorant.product_tmpl_id.colorant_code or '').strip().upper()
            if code and code.startswith('C') and code not in mapped:
                mapped[code] = colorant
        return mapped

    @api.model
    def _get_colorant_code_sequence(self, colorants_by_code):
        def sort_key(code):
            suffix = code[1:] if code.startswith('C') else code
            return (0, int(suffix)) if suffix.isdigit() else (1, code)

        expected = ['C%s' % index for index in range(1, 17)]
        ordered = [code for code in expected if code in colorants_by_code]
        extra = sorted(
            [code for code in colorants_by_code if code not in expected],
            key=sort_key,
        )
        return ordered + extra

    def _build_formula_payload(self):
        self.ensure_one()
        formula = {}
        for wizard_line in self.line_ids:
            if wizard_line.shots <= 0:
                continue
            code = wizard_line.colorant_code
            if not code:
                raise ValidationError(_("Colourant %s has no colourant code.") % wizard_line.colorant_id.display_name)
            if code in formula:
                formula[code]['shots'] += wizard_line.shots
            else:
                formula[code] = {
                    'shots': wizard_line.shots,
                    'unit_cost_excl_vat': wizard_line.unit_cost_excl_vat or 0.0,
                }
        return formula

    def _snapshot_line(self, line):
        return {
            'formula': self._parse_formula(line.tinting_formula_json),
            'quoted_base_cost': line.quoted_base_cost,
            'quoted_colorant_cost': line.quoted_colorant_cost,
            'quoted_cost_at_creation': line.quoted_cost_at_creation,
            'price_unit': line.price_unit,
            'colour_code_id': line.colour_code_id.id,
            'fandeck_id': line.fandeck_id.id,
            'base_category_id': line.base_category_id.id,
            'base_product_id': line.base_product_id.id,
            'base_product_uom_id': line.base_product_uom_id.id,
        }

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Edit Tint / Colourants'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
