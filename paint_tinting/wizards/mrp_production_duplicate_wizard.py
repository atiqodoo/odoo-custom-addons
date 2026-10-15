# -*- coding: utf-8 -*-
import logging

from odoo import Command, models, fields, api, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class MrpProductionDuplicateWizard(models.TransientModel):
    _name = 'mrp.production.duplicate.wizard'
    _description = 'Duplicate Tinting MO Wizard'

    source_mo_id = fields.Many2one(
        'mrp.production',
        string='Source MO',
        required=True,
        readonly=True
    )

    product_name = fields.Char(
        string='Product',
        readonly=True
    )

    quantity = fields.Integer(
        string='Number of Duplicates',
        required=True,
        default=1,
        help='How many identical MOs to create'
    )

    auto_confirm = fields.Boolean(
        string='Auto-Confirm MOs',
        default=True,
        help='Automatically confirm the duplicated MOs'
    )

    # ----------------------------------------------------------------
    # SOURCE SO - carried from the exists-wizard so we can return after production
    # ----------------------------------------------------------------
    source_sale_order_id = fields.Many2one(
        'sale.order',
        string='Return to Sales Order',
        readonly=True,
        help='After duplicating, clicking "Return to SO" opens this order.',
    )
    source_sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Source SO Line',
        readonly=True,
        help='SO line to update with the tinted product after duplication.',
    )

    # ----------------------------------------------------------------
    # SELLING PRICE - required per lot; each duplicate gets this price
    # (can be edited individually on the MO after creation)
    # ----------------------------------------------------------------
    selling_price = fields.Float(
        string='Selling Price (KES incl. VAT)',
        digits='Product Price',
        required=True,
        default=0.0,
        help='Selling price for each duplicated MO/lot. '
             'Each lot must be priced - you can edit individual MOs afterwards.',
    )

    source_total_cost = fields.Float(
        string='Total Cost (incl. VAT)',
        related='source_mo_id.mo_total_cost',
        readonly=True,
        digits='Product Price',
    )

    preview_message = fields.Html(
        string='Preview',
        compute='_compute_preview_message'
    )

    @api.depends('quantity', 'source_mo_id', 'product_name', 'selling_price', 'source_total_cost')
    def _compute_preview_message(self):
        for wizard in self:
            if wizard.source_mo_id and wizard.quantity > 0:
                uom = wizard.source_mo_id.product_uom_id.name
                price = wizard.selling_price
                cost = wizard.source_total_cost
                profit = price - cost if price > 0 else 0.0
                margin = (profit / price * 100) if price > 0 else 0.0
                price_color = '#4caf50' if profit >= 0 else '#f44336'
                pc = price_color  # short alias to keep HTML lines below 100 chars
                price_cell = (
                    f'<td style="padding:4px;color:{pc};">'
                    f'<strong>{price:,.2f} KES</strong></td>'
                )
                profit_cell = (
                    f'<td style="padding:4px;color:{pc};">'
                    f'{profit:,.2f} KES ({margin:.1f}%)</td>'
                )
                wizard.preview_message = f"""
                <div style="padding:15px;background:#f0f8ff;
                            border-left:4px solid #2196F3;">
                    <h4 style="margin-top:0;">Preview</h4>
                    <table style="width:100%;border-collapse:collapse;">
                        <tr>
                            <td style="padding:4px;"><strong>Product:</strong></td>
                            <td style="padding:4px;">{wizard.product_name}</td>
                        </tr>
                        <tr>
                            <td style="padding:4px;"><strong>MOs to create:</strong></td>
                            <td style="padding:4px;">{wizard.quantity} x 1.0 {uom}</td>
                        </tr>
                        <tr>
                            <td style="padding:4px;"><strong>Cost per MO:</strong></td>
                            <td style="padding:4px;">{cost:,.2f} KES</td>
                        </tr>
                        <tr style="background:#e3f2fd;">
                            <td style="padding:4px;">
                                <strong>Selling Price per MO:</strong>
                            </td>
                            {price_cell}
                        </tr>
                        <tr>
                            <td style="padding:4px;"><strong>Profit per MO:</strong></td>
                            {profit_cell}
                        </tr>
                    </table>
                    <p style="margin:8px 0 0;color:#666;font-size:0.9em;">
                        Same BOM and formula. Edit price individually on each MO.
                    </p>
                </div>
                """
            else:
                wizard.preview_message = '<p>Enter quantity to see preview</p>'

    @api.constrains('quantity')
    def _check_quantity(self):
        for wizard in self:
            if wizard.quantity < 1:
                raise ValidationError(_('Quantity must be at least 1.'))
            if wizard.quantity > 100:
                raise ValidationError(_(
                    'Maximum 100 MOs can be created at once.\n'
                    'For larger quantities, run this wizard multiple times.'
                ))

    @api.constrains('selling_price')
    def _check_selling_price(self):
        for wizard in self:
            if wizard.selling_price <= 0:
                raise ValidationError(_('Selling price must be greater than zero.'))
            below_cost = (
                wizard.source_total_cost > 0
                and wizard.selling_price < wizard.source_total_cost
            )
            if below_cost:
                raise ValidationError(_(
                    'Selling price (%(price).2f KES) is below total cost (%(cost).2f KES).\n'
                    'Please enter a price at or above the total cost to avoid a loss.',
                    price=wizard.selling_price,
                    cost=wizard.source_total_cost,
                ))

    def action_duplicate_mos(self):
        self.ensure_one()

        if not self.source_mo_id.is_tinting_mo:
            raise ValidationError(_('Source MO must be a tinting Manufacturing Order.'))

        if self.selling_price <= 0:
            raise ValidationError(_(
                'Please enter a selling price greater than zero before duplicating.'
            ))

        source_sale_order = self.source_sale_order_id or self.source_mo_id.source_sale_order_id
        source_sale_order_line = (
            self.source_sale_order_line_id
            or self.source_mo_id.source_sale_order_line_id
        )
        partner = source_sale_order.partner_id or self.source_mo_id.partner_id
        created_mos = self.env['mrp.production']
        duplicate_bom = self._prepare_duplicate_bom()
        uses_recipe_revision = duplicate_bom != self.source_mo_id.bom_id
        _logger.info(
            "[PAINT_TINTING][TINT_DUPLICATE_BATCH][START] wizard_id=%s "
            "source_mo_id=%s source_bom_id=%s duplicate_bom_id=%s "
            "recipe_revision=%s quantity=%s source_sale_order_id=%s "
            "source_sale_order_line_id=%s partner_id=%s user_id=%s",
            self.id, self.source_mo_id.id, self.source_mo_id.bom_id.id,
            duplicate_bom.id, uses_recipe_revision, self.quantity,
            source_sale_order.id, source_sale_order_line.id, partner.id,
            self.env.user.id,
        )

        # Update the originating SO line before manufacturing so the delivery
        # move is for the tinted product and can reserve the new finished lot.
        if source_sale_order_line:
            sol = source_sale_order_line
            tinted_product = self.source_mo_id.product_id
            update_vals = {'tinted_product_created': True}
            if sol.product_id != tinted_product:
                update_vals['product_id'] = tinted_product.id
            if self.selling_price > 0:
                update_vals['price_unit'] = self.selling_price
            sol.write(update_vals)

        for i in range(self.quantity):
            copy_values = {
                'origin': f"Duplicate {i + 1} of {self.source_mo_id.name}",
                'source_mo_id': self.source_mo_id.id,
                'product_qty': 1.0,
                'state': 'draft',
                'mo_selling_price': self.selling_price,
                'bom_id': duplicate_bom.id,
                'partner_id': partner.id,
                'source_sale_order_id': source_sale_order.id,
                'source_sale_order_line_id': source_sale_order_line.id,
            }
            if uses_recipe_revision:
                # A done MO normally copies its historical raw moves. Clear
                # them and rebuild from the new revision before confirmation.
                copy_values['move_raw_ids'] = [Command.clear()]
            new_mo = self.source_mo_id.copy(copy_values)

            if uses_recipe_revision:
                new_mo._compute_move_raw_ids()
                _logger.info(
                    "TINT_DUPLICATE_RAW_MOVES_REBUILT new_mo_id=%s bom_id=%s moves=%s",
                    new_mo.id, duplicate_bom.id,
                    [(move.product_id.id, move.bom_line_id.id, move.product_uom_qty)
                     for move in new_mo.move_raw_ids],
                )

            if self.auto_confirm:
                new_mo.action_confirm()

            if uses_recipe_revision:
                for move in new_mo.move_raw_ids.filtered('bom_line_id'):
                    exact_quantity = move.bom_line_id.product_qty
                    move.write({
                        'product_uom_qty': exact_quantity,
                        'quantity': exact_quantity,
                    })

            # When the duplicate flow was launched from an SO, the cashier
            # needs a real finished lot before returning to the order/POS.
            # Creating only a confirmed MO leaves the order line pointing to
            # stock that does not exist yet.
            if source_sale_order_line and new_mo.state != 'done':
                self._produce_tinting_duplicate_now(new_mo)

            created_mos |= new_mo

        _logger.info(
            "[PAINT_TINTING][TINT_DUPLICATE_BATCH][END] wizard_id=%s "
            "created_mo_ids=%s duplicate_bom_id=%s source_sale_order_id=%s "
            "source_sale_order_line_id=%s",
            self.id, created_mos.ids, duplicate_bom.id,
            source_sale_order.id, source_sale_order_line.id,
        )

        # If triggered from an SO flow, return to that SO after duplication
        if source_sale_order:
            return {
                'type': 'ir.actions.act_window',
                'name': source_sale_order.name,
                'res_model': 'sale.order',
                'res_id': source_sale_order.id,
                'view_mode': 'form',
                'target': 'current',
            }

        return {
            'type': 'ir.actions.act_window',
            'name': _('Duplicated Manufacturing Orders'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_mos.ids)],
            'context': {'create': False},
            'target': 'current',
        }

    def _prepare_duplicate_bom(self):
        """Extension hook: default duplicates continue using the source BOM."""
        self.ensure_one()
        return self.source_mo_id.bom_id

    def _produce_tinting_duplicate_now(self, production):
        """Produce a duplicated tinting MO immediately for the SO/POS flow."""
        for mo in production:
            if mo.state == 'draft':
                mo.action_confirm()

            if mo.product_tracking in ('lot', 'serial') and not mo.lot_producing_id:
                mo.action_generate_serial()

            if not mo.qty_producing:
                mo.qty_producing = mo.product_qty
                mo.set_qty_producing()

            result = mo.with_context(skip_redirection=True).button_mark_done()
            if result is not True and mo.state != 'done':
                raise ValidationError(_(
                    'The duplicated MO %(mo)s could not be manufactured automatically.',
                    mo=mo.name,
                ))
