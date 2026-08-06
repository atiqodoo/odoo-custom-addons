import logging

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html_escape
from odoo.tools.float_utils import float_compare

from ..services.substitution_mismatch import (
    build_mismatch_rows,
    format_qty,
    mismatch_fingerprint,
)
from .promotion_override_log import SYSTEM_CONTEXT_KEY


_logger = logging.getLogger(__name__)


class VendorPromotionFocSubstitutionWizard(models.TransientModel):
    _name = 'vendor.promotion.foc.substitution.wizard'
    _description = 'Promotion FOC Substitute Picker'

    picking_id = fields.Many2one('stock.picking', required=True, readonly=True)
    available_move_ids = fields.Many2many(
        'stock.move',
        compute='_compute_available_move_ids',
    )
    total_substitute_qty = fields.Float(
        compute='_compute_total_substitute_qty',
        readonly=True,
    )
    foc_line_ids = fields.One2many(
        'vendor.promotion.foc.substitution.wizard.line',
        'wizard_id',
        string='FOC Receipt Lines',
    )
    substitution_reason = fields.Char(
        string='Reason',
        default='Vendor delivered alternate eligible FOC variant',
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        picking = self.env['stock.picking'].browse(self.env.context.get('default_picking_id'))
        if picking.exists():
            moves = picking._promotion_foc_substitution_moves()
            values['picking_id'] = picking.id
            values['foc_line_ids'] = [
                (0, 0, {
                    'move_id': move.id,
                    'substitute_line_ids': self._substitute_commands_for_move(move),
                })
                for move in moves
            ]
        return values

    @api.depends('picking_id')
    def _compute_available_move_ids(self):
        for wizard in self:
            if wizard.picking_id:
                wizard.available_move_ids = wizard.picking_id._promotion_foc_substitution_moves()
            else:
                wizard.available_move_ids = self.env['stock.move']

    @api.depends('foc_line_ids.substitute_line_ids.quantity')
    def _compute_total_substitute_qty(self):
        for wizard in self:
            wizard.total_substitute_qty = sum(wizard.foc_line_ids.mapped('substitute_line_ids.quantity'))

    def _eligible_products_for_move(self, move):
        if not move or not move.purchase_line_id or not move.purchase_line_id.is_promotion_foc:
            return self.env['product.product']
        rule = move.purchase_line_id.promotion_id
        policy = rule.effective_substitution_policy() if rule else 'none'
        if policy == 'none':
            return move.product_id
        if policy == 'requested_variants':
            return move.purchase_line_id.promotion_qualifying_line_ids.mapped('product_id') or move.product_id
        templates = rule.product_tmpl_ids | rule.product_tmpl_id
        products = self.env['product.product'].search([
            ('active', '=', True),
            ('product_tmpl_id', 'in', templates.ids),
        ]) if templates else move.product_id
        if rule.product_id:
            products |= rule.product_id
        return products

    def _substitute_commands_for_move(self, move):
        commands = []
        products = self._eligible_products_for_move(move).sorted(
            key=lambda product: (
                product.display_name or '',
                product.default_code or '',
                product.id,
            )
        )
        for product in products:
            commands.append((0, 0, {
                'product_id': product.id,
                'quantity': 0.0,
            }))
        return commands

    def _validate_lines(self):
        self.ensure_one()
        if not self.foc_line_ids:
            raise ValidationError(_('Add at least one FOC receipt line.'))
        grouped = {}
        for foc_line in self.foc_line_ids:
            move = foc_line.move_id
            if not move:
                raise ValidationError(_('Each FOC section must select a FOC receipt line.'))
            if move not in self.available_move_ids:
                raise ValidationError(_('FOC receipt line %s does not belong to this receipt.') % move.display_name)
            _logger.info(
                '[VPP_SUBSTITUTE_INPUT] picking_id=%s move_id=%s purchase_line_id=%s user_id=%s rows=%s',
                self.picking_id.id,
                move.id,
                move.purchase_line_id.id,
                self.env.user.id,
                [
                    (line.product_id.id, line.product_id.display_name, line.quantity)
                    for line in foc_line.substitute_line_ids
                    if line.product_id or line.quantity
                ],
            )
            positive_lines = foc_line.substitute_line_ids.filtered(
                lambda line: float_compare(
                    line.quantity,
                    0.0,
                    precision_rounding=move.product_uom.rounding or 0.01,
                ) > 0
            )
            incomplete_lines = positive_lines.filtered(lambda line: not line.product_id)
            if incomplete_lines:
                _logger.warning(
                    '[VPP_SUBSTITUTE_IGNORED_INCOMPLETE] picking_id=%s move_id=%s user_id=%s lines=%s',
                    self.picking_id.id,
                    move.id,
                    self.env.user.id,
                    [(line.id, line.quantity) for line in incomplete_lines],
                )
                raise ValidationError(_(
                    'Some delivered FOC quantities were submitted without a delivered variant. '
                    'Please reopen the substitute wizard and apply again.'
                ))
            substitute_lines = positive_lines.filtered(lambda line: line.product_id)
            if not substitute_lines:
                _logger.info(
                    '[VPP_SUBSTITUTE_SKIPPED_EMPTY] picking_id=%s move_id=%s purchase_line_id=%s user_id=%s',
                    self.picking_id.id,
                    move.id,
                    move.purchase_line_id.id,
                    self.env.user.id,
                )
                continue
            eligible_products = self._eligible_products_for_move(move)
            rounding = move.product_uom.rounding or 0.01
            total_qty = 0.0
            promised_qty = move.purchase_line_id.product_qty
            for line in substitute_lines:
                if not line.product_id or line.product_id not in eligible_products:
                    raise ValidationError(_('Product %s is not eligible for promotion substitution on %s.') % (
                        line.product_id.display_name or '-',
                        move.display_name,
                    ))
                total_qty += line.quantity
            if float_compare(total_qty, promised_qty, precision_rounding=rounding) > 0:
                _logger.warning(
                    '[VPP_SUBSTITUTE_BLOCKED] picking_id=%s move_id=%s user_id=%s total_qty=%s promised_qty=%s lines=%s',
                    self.picking_id.id,
                    move.id,
                    self.env.user.id,
                    total_qty,
                    promised_qty,
                    [(line.product_id.id, line.quantity) for line in substitute_lines],
                )
                raise ValidationError(_(
                    'Delivered FOC quantity %(total)s cannot exceed qualified promotion FOC quantity %(promised)s for %(line)s.',
                    total=total_qty,
                    promised=promised_qty,
                    line=move.display_name,
                ))
            grouped[move.id] = substitute_lines
        if not grouped:
            raise ValidationError(_('Enter quantity on at least one eligible substitute line before applying.'))
        return grouped

    def _substitute_uom_for_line(self, source_move, line):
        product = line.product_id
        uom = source_move.product_uom
        if product.uom_id.category_id == source_move.product_uom.category_id:
            uom = product.uom_id
        return uom

    def _move_values_for_line(self, source_move, line, for_create=True, demand_qty=None):
        product = line.product_id
        uom = self._substitute_uom_for_line(source_move, line)
        demand_qty = line.quantity if demand_qty is None else demand_qty
        values = {
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': demand_qty,
            'quantity': line.quantity,
            'picked': True,
            'product_uom': uom.id,
            'picking_id': source_move.picking_id.id,
            'picking_type_id': source_move.picking_type_id.id,
            'location_id': source_move.location_id.id,
            'location_dest_id': source_move.location_dest_id.id,
            'purchase_line_id': source_move.purchase_line_id.id,
            'partner_id': source_move.partner_id.id,
            'company_id': source_move.company_id.id,
            'price_unit': 0.0,
            'origin': source_move.origin,
            'group_id': source_move.group_id.id,
            'procure_method': source_move.procure_method,
        }
        if for_create:
            values['state'] = 'draft'
        return values

    def _mark_entered_receipt_quantities_picked(self):
        self.ensure_one()
        moves = self.picking_id.move_ids.filtered(
            lambda move: move.state not in ('done', 'cancel')
            and float_compare(
                move.quantity,
                0.0,
                precision_rounding=move.product_uom.rounding or 0.01,
            ) > 0
        )
        if moves:
            moves.write({'picked': True})
            _logger.info(
                '[VPP_SUBSTITUTE_PICKED_SYNC] picking_id=%s picking_name=%s user_id=%s move_ids=%s lines=%s',
                self.picking_id.id,
                self.picking_id.name,
                self.env.user.id,
                moves.ids,
                [
                    {
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'purchase_line_id': move.purchase_line_id.id,
                        'is_foc': move.purchase_line_id.is_promotion_foc,
                        'demand_qty': move.product_uom_qty,
                        'done_qty': move.quantity,
                        'picked': move.picked,
                    }
                    for move in moves
                ],
            )

    def _substitution_mismatch_log_line_commands(self, mismatch_rows):
        return [(0, 0, {
            'application_id': row['application'].id,
            'foc_line_id': row['foc_line'].id,
            'source_move_id': row['source_move'].id,
            'expected_product_id': row['expected_product'].id,
            'substitute_product_id': row['substitute_product'].id,
            'substitute_uom_id': row['substitute_uom'].id,
            'substitute_category_id': row['substitute_category'].id,
            'substitute_qty': row['quantity'],
            'charged_line_ids': [(6, 0, row['charged_lines'].ids)],
            'charged_uom_ids': [(6, 0, row['charged_uoms'].ids)],
            'charged_category_ids': [(6, 0, row['charged_categories'].ids)],
        }) for row in mismatch_rows]

    def _substitution_mismatch_purchase(self, mismatch_rows):
        purchases = self.env['purchase.order']
        for row in mismatch_rows:
            purchases |= row['foc_line'].order_id
        return purchases[:1]

    def _substitution_mismatch_get_log(self, mismatch_rows, fingerprint):
        self.ensure_one()
        Log = self.env['vendor.promotion.substitution.override.log']
        log = Log.search([
            ('picking_id', '=', self.picking_id.id),
            ('user_id', '=', self.env.user.id),
            ('fingerprint', '=', fingerprint),
            ('override_used', '=', False),
        ], order='id desc', limit=1)
        if not log:
            purchase = self._substitution_mismatch_purchase(mismatch_rows)
            created_log = Log.sudo().with_context(**{SYSTEM_CONTEXT_KEY: True}).create({
                'picking_id': self.picking_id.id,
                'purchase_id': purchase.id,
                'company_id': self.picking_id.company_id.id,
                'partner_id': self.picking_id.partner_id.commercial_partner_id.id,
                'user_id': self.env.user.id,
                'fingerprint': fingerprint,
                'line_ids': self._substitution_mismatch_log_line_commands(mismatch_rows),
            })
            log = Log.browse(created_log.id)
        return log

    def _substitution_mismatch_message(self, mismatch_rows, dismissal_count, dismissal_limit):
        lines = [
            _('FOC substitute UoM/category mismatch. Apply Substitute has been paused.'),
            '',
        ]
        for row in mismatch_rows:
            charged_uoms = ', '.join(row['charged_uoms'].mapped('display_name')) or '-'
            charged_categories = ', '.join(row['charged_categories'].mapped('display_name')) or '-'
            lines.extend([
                _('%(substitute)s x %(qty)s',
                  substitute=row['substitute_product'].display_name,
                  qty=format_qty(row['quantity'])),
                _('Expected FOC: %(expected)s',
                  expected=row['expected_product'].display_name),
                _('Substitute UoM/category: %(uom)s / %(category)s',
                  uom=row['substitute_uom'].display_name,
                  category=row['substitute_category'].display_name),
                _('Qualifying charged UoM/category: %(uoms)s / %(categories)s',
                  uoms=charged_uoms,
                  categories=charged_categories),
                '',
            ])
        remaining = max(dismissal_limit - dismissal_count, 0)
        lines.append(
            _('Close this warning %(remaining)s more time(s) to enable an audited substitute override.',
              remaining=remaining)
        )
        return '\n'.join(lines)

    def _substitution_mismatch_warning_action(self, log, mismatch_rows, fingerprint):
        self.ensure_one()
        shown_count = log.warning_shown_count + 1
        log.sudo().with_context(**{SYSTEM_CONTEXT_KEY: True}).write({
            'warning_shown_count': shown_count,
        })
        log._create_event('warning_shown', {
            'warning_shown_count': shown_count,
            'dismissal_count': log.dismissal_count,
            'picking_name': self.picking_id.name,
        })
        dismissal_limit = log._dismissal_limit()
        _logger.warning(
            '[VPP_SUBSTITUTE_BLOCK] picking_id=%s picking_name=%s log_id=%s user_id=%s '
            'shown_count=%s dismissal_count=%s dismissal_limit=%s fingerprint=%s rows=%s',
            self.picking_id.id,
            self.picking_id.name,
            log.id,
            self.env.user.id,
            shown_count,
            log.dismissal_count,
            dismissal_limit,
            fingerprint,
            [
                {
                    'source_move_id': row['source_move'].id,
                    'expected_product_id': row['expected_product'].id,
                    'substitute_product_id': row['substitute_product'].id,
                    'substitute_qty': row['quantity'],
                    'substitute_uom_id': row['substitute_uom'].id,
                    'substitute_category_id': row['substitute_category'].id,
                    'charged_line_ids': row['charged_lines'].ids,
                    'charged_uom_ids': row['charged_uoms'].ids,
                    'charged_category_ids': row['charged_categories'].ids,
                }
                for row in mismatch_rows
            ],
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'vendor_purchase_promotions.substitution_mismatch_warning',
            'params': {
                'title': _('FOC Substitute Mismatch - Apply Paused'),
                'message': self._substitution_mismatch_message(
                    mismatch_rows,
                    log.dismissal_count,
                    dismissal_limit,
                ),
                'log_id': log.id,
                'fingerprint': fingerprint,
                'dismissal_count': log.dismissal_count,
            },
        }

    def _substitution_mismatch_mark_override_confirmed(self, log, mismatch_rows):
        self.ensure_one()
        confirmed_at = fields.Datetime.now()
        log.sudo().with_context(**{SYSTEM_CONTEXT_KEY: True}).write({
            'override_used': True,
            'override_confirmed_at': confirmed_at,
        })
        log._create_event('override_confirmed', {
            'dismissal_count': log.dismissal_count,
            'picking_state': self.picking_id.state,
            'picking_name': self.picking_id.name,
        })
        detail_rows = ''.join(
            '<li>%s x %s; substitute UoM/category %s / %s; qualifying UoMs %s; qualifying categories %s</li>' % (
                html_escape(row['substitute_product'].display_name),
                html_escape(format_qty(row['quantity'])),
                html_escape(row['substitute_uom'].display_name),
                html_escape(row['substitute_category'].display_name),
                html_escape(', '.join(row['charged_uoms'].mapped('display_name')) or '-'),
                html_escape(', '.join(row['charged_categories'].mapped('display_name')) or '-'),
            )
            for row in mismatch_rows
        )
        self.picking_id.message_post(body=Markup(
            '<b>%s</b><br/>%s<ul>%s</ul>' % (
                html_escape(_('FOC substitute mismatch override used')),
                html_escape(_('The user dismissed the substitute mismatch warning three times and applied the substitute anyway.')),
                detail_rows,
            )
        ))
        _logger.warning(
            '[VPP_SUBSTITUTE_OVERRIDE] picking_id=%s picking_name=%s log_id=%s user_id=%s '
            'dismissal_count=%s fingerprint=%s line_count=%s',
            self.picking_id.id,
            self.picking_id.name,
            log.id,
            self.env.user.id,
            log.dismissal_count,
            log.fingerprint,
            len(mismatch_rows),
        )

    def _substitution_mismatch_guard(self, grouped_lines):
        self.ensure_one()
        mismatch_rows = build_mismatch_rows(self.env, grouped_lines)
        if not mismatch_rows:
            _logger.info(
                '[VPP_SUBSTITUTE_MATCH] picking_id=%s picking_name=%s user_id=%s grouped_move_ids=%s',
                self.picking_id.id,
                self.picking_id.name,
                self.env.user.id,
                list(grouped_lines),
            )
            return False, self.env['vendor.promotion.substitution.override.log'], mismatch_rows

        fingerprint = mismatch_fingerprint(self.env, self.picking_id, mismatch_rows)
        log = self._substitution_mismatch_get_log(mismatch_rows, fingerprint)
        dismissal_limit = log._dismissal_limit()
        if not log.override_available or log.dismissal_count < dismissal_limit:
            return self._substitution_mismatch_warning_action(
                log,
                mismatch_rows,
                fingerprint,
            ), log, mismatch_rows

        _logger.info(
            '[VPP_SUBSTITUTE_READY] picking_id=%s picking_name=%s log_id=%s user_id=%s '
            'dismissal_count=%s fingerprint=%s',
            self.picking_id.id,
            self.picking_id.name,
            log.id,
            self.env.user.id,
            log.dismissal_count,
            fingerprint,
        )
        return False, log, mismatch_rows

    def action_apply_substitution(self):
        self.ensure_one()
        if self.picking_id.state in ('done', 'cancel'):
            raise UserError(_('FOC substitution cannot be changed after the receipt is done or cancelled.'))
        grouped_lines = self._validate_lines()
        guard_action, mismatch_log, mismatch_rows = self._substitution_mismatch_guard(grouped_lines)
        if guard_action:
            return guard_action
        all_created_moves = self.env['stock.move']
        affected_purchase_lines = self.env['purchase.order.line']
        body_lines = []

        for source_move_id, lines in grouped_lines.items():
            source_move = self.env['stock.move'].browse(source_move_id)
            if not source_move.purchase_line_id.is_promotion_foc:
                raise UserError(_('Only promotion FOC receipt lines can be substituted.'))
            original_product = source_move.product_id
            old_moves = source_move.purchase_line_id.move_ids.filtered(
                lambda move: move.picking_id == self.picking_id
                and move.state not in ('done', 'cancel')
                and move.purchase_line_id == source_move.purchase_line_id
            )
            extra_moves = old_moves - source_move
            if extra_moves:
                extra_moves._action_cancel()
                _logger.info(
                    '[VPP_SUBSTITUTE] cancelled_prior_extra_moves picking_id=%s move_ids=%s source_move_id=%s',
                    self.picking_id.id,
                    extra_moves.ids,
                    source_move.id,
                )

            first_line = lines[:1]
            source_demand_qty = source_move.product_uom_qty
            total_qty = sum(lines.mapped('quantity'))
            first_line_demand_qty = first_line.quantity
            first_line_uom = self._substitute_uom_for_line(source_move, first_line)
            if float_compare(
                total_qty,
                source_demand_qty,
                precision_rounding=source_move.product_uom.rounding or 0.01,
            ) < 0:
                missing_qty = source_demand_qty - total_qty
                if first_line_uom.category_id == source_move.product_uom.category_id:
                    missing_qty = source_move.product_uom._compute_quantity(
                        missing_qty,
                        first_line_uom,
                        rounding_method='HALF-UP',
                    )
                first_line_demand_qty = first_line.quantity + missing_qty
                _logger.warning(
                    '[VPP_SUBSTITUTE_PARTIAL_DEMAND] picking_id=%s picking_name=%s source_move_id=%s '
                    'purchase_line_id=%s source_demand_qty=%s delivered_qty=%s first_line_product_id=%s '
                    'first_line_done_qty=%s first_line_demand_qty=%s source_uom_id=%s first_line_uom_id=%s',
                    self.picking_id.id,
                    self.picking_id.name,
                    source_move.id,
                    source_move.purchase_line_id.id,
                    source_demand_qty,
                    total_qty,
                    first_line.product_id.id,
                    first_line.quantity,
                    first_line_demand_qty,
                    source_move.product_uom.id,
                    first_line_uom.id,
                )
            source_move.write(self._move_values_for_line(
                source_move,
                first_line,
                for_create=False,
                demand_qty=first_line_demand_qty,
            ))
            source_move.write({'picked': True})
            created_moves = self.env['stock.move']
            for line in lines[1:]:
                created_moves |= self.env['stock.move'].create(
                    self._move_values_for_line(source_move, line, for_create=True)
                )
            if created_moves:
                created_moves._action_confirm()._action_assign()
                created_moves.write({'picked': True})
            if source_move.state == 'draft':
                source_move._action_confirm()._action_assign()
                source_move.write({'picked': True})
            all_created_moves |= created_moves
            affected_purchase_lines |= source_move.purchase_line_id

            total_qty = sum(lines.mapped('quantity'))
            line_summary = ', '.join(
                '%s x %s' % (line.product_id.display_name, line.quantity)
                for line in lines
            )
            body_lines.append('%s: %s replaced by %s' % (
                source_move.purchase_line_id.display_name,
                original_product.display_name,
                line_summary,
            ))
            _logger.warning(
                '[VPP_SUBSTITUTE] picking_id=%s picking_name=%s source_move_id=%s created_move_ids=%s '
                'purchase_line_id=%s promotion_id=%s old_product_id=%s total_qty=%s promised_qty=%s '
                'user_id=%s reason=%s source_demand=%s source_done=%s source_picked=%s lines=%s',
                self.picking_id.id,
                self.picking_id.name,
                source_move.id,
                created_moves.ids,
                source_move.purchase_line_id.id,
                source_move.purchase_line_id.promotion_id.id,
                original_product.id,
                total_qty,
                source_move.purchase_line_id.product_qty,
                self.env.user.id,
                self.substitution_reason,
                source_move.product_uom_qty,
                source_move.quantity,
                source_move.picked,
                [(line.product_id.id, line.quantity) for line in lines],
            )

        self._mark_entered_receipt_quantities_picked()
        applications = self.env['vendor.purchase.promotion.application'].search([
            ('foc_line_id', 'in', affected_purchase_lines.ids),
        ])
        if applications:
            applications._compute_foc_status()
            applications.bill_ids._sync_promotion_payment_hold()
        if mismatch_log and mismatch_rows:
            self._substitution_mismatch_mark_override_confirmed(mismatch_log, mismatch_rows)

        body = _(
            'Promotion FOC substitutes applied: %(lines)s. Reason: %(reason)s',
            lines='; '.join(body_lines),
            reason=self.substitution_reason or '-',
        )
        self.picking_id.message_post(body=body)
        return {'type': 'ir.actions.act_window_close'}


class VendorPromotionFocSubstitutionWizardLine(models.TransientModel):
    _name = 'vendor.promotion.foc.substitution.wizard.line'
    _description = 'Promotion FOC Substitute Picker FOC Line'

    wizard_id = fields.Many2one(
        'vendor.promotion.foc.substitution.wizard',
        required=True,
        ondelete='cascade',
    )
    eligible_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_eligible_product_ids',
    )
    available_move_ids = fields.Many2many(
        related='wizard_id.available_move_ids',
        readonly=True,
    )
    move_id = fields.Many2one(
        'stock.move',
        string='FOC Receipt Line',
        required=True,
        domain="[('id', 'in', available_move_ids)]",
    )
    expected_product_id = fields.Many2one(
        'product.product',
        related='move_id.product_id',
        readonly=True,
    )
    promotion_id = fields.Many2one(
        'vendor.purchase.promotion',
        related='move_id.purchase_line_id.promotion_id',
        readonly=True,
    )
    promised_foc_qty = fields.Float(
        related='move_id.purchase_line_id.product_qty',
        readonly=True,
    )
    total_substitute_qty = fields.Float(
        compute='_compute_total_substitute_qty',
        readonly=True,
    )
    delivered_summary = fields.Char(
        compute='_compute_delivered_summary',
        readonly=True,
    )
    substitute_line_ids = fields.One2many(
        'vendor.promotion.foc.substitution.wizard.substitute.line',
        'wizard_line_id',
        string='Delivered Substitute Variants',
    )

    @api.depends('substitute_line_ids.quantity')
    def _compute_total_substitute_qty(self):
        for line in self:
            line.total_substitute_qty = sum(line.substitute_line_ids.mapped('quantity'))

    @api.depends('substitute_line_ids.product_id', 'substitute_line_ids.quantity')
    def _compute_delivered_summary(self):
        for line in self:
            parts = [
                '%s x %s' % (sub.product_id.display_name, sub.quantity)
                for sub in line.substitute_line_ids
                if sub.product_id and sub.quantity
            ]
            line.delivered_summary = ', '.join(parts)

    @api.depends('move_id')
    def _compute_eligible_product_ids(self):
        for line in self:
            if line.wizard_id and line.move_id:
                line.eligible_product_ids = line.wizard_id._eligible_products_for_move(line.move_id)
            else:
                line.eligible_product_ids = self.env['product.product']

    @api.onchange('move_id')
    def _onchange_move_id(self):
        for line in self:
            if line.move_id and not line.substitute_line_ids:
                line.substitute_line_ids = line.wizard_id._substitute_commands_for_move(line.move_id)
            elif not line.move_id:
                line.substitute_line_ids = [(5, 0, 0)]


class VendorPromotionFocSubstitutionWizardSubstituteLine(models.TransientModel):
    _name = 'vendor.promotion.foc.substitution.wizard.substitute.line'
    _description = 'Promotion FOC Substitute Picker Delivered Variant'

    wizard_line_id = fields.Many2one(
        'vendor.promotion.foc.substitution.wizard.line',
        required=True,
        ondelete='cascade',
    )
    wizard_id = fields.Many2one(
        'vendor.promotion.foc.substitution.wizard',
        related='wizard_line_id.wizard_id',
        readonly=True,
    )
    eligible_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_eligible_product_ids',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Delivered Variant',
        domain="[('id', 'in', eligible_product_ids)]",
    )
    quantity = fields.Float(required=True, default=0.0)

    @api.depends('wizard_line_id', 'wizard_line_id.eligible_product_ids')
    def _compute_eligible_product_ids(self):
        for line in self:
            line.eligible_product_ids = line.wizard_line_id.eligible_product_ids

    @api.onchange('wizard_line_id')
    def _onchange_wizard_line_id(self):
        for line in self:
            eligible_ids = line.wizard_line_id.eligible_product_ids.ids
            return {'domain': {'product_id': [('id', 'in', eligible_ids)]}}
