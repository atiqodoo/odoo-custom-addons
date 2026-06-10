# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


_logger = logging.getLogger(__name__)


class ResPartnerLoyaltyImportExport(models.Model):
    _inherit = 'res.partner'

    loyalty_balance_points = fields.Float(
        string='Loyalty Balance Points',
        compute='_compute_loyalty_balance_points',
        inverse='_inverse_loyalty_balance_points',
        readonly=False,
        help=(
            'Import/export helper for the primary customer loyalty card balance. '
            'Importing this field updates loyalty.card.points and registers a '
            'standard loyalty history line.'
        ),
    )

    def _lpm_get_primary_loyalty_card(self):
        """Return the primary loyalty card used for import/export."""
        self.ensure_one()
        card = self.env['loyalty.card'].sudo().search([
            ('partner_id', '=', self.id),
            ('program_id.program_type', '=', 'loyalty'),
            ('program_id.active', '=', True),
        ], order='id asc', limit=1)
        _logger.debug(
            "[loyalty_import_export] card lookup | partner_id=%s | partner=%r | card_id=%s | points=%s",
            self.id, self.display_name, card.id if card else False, card.points if card else None,
        )
        return card

    def _lpm_get_primary_loyalty_program(self):
        """Return the loyalty program used when import must create a card."""
        company = self.env.company
        program = self.env['loyalty.program'].sudo().search([
            ('program_type', '=', 'loyalty'),
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], order='id asc', limit=1)
        _logger.debug(
            "[loyalty_import_export] program lookup | company_id=%s | program_id=%s | program=%r",
            company.id, program.id if program else False, program.name if program else None,
        )
        return program

    def _lpm_get_or_create_primary_loyalty_card(self, target_points):
        """Find or create the primary loyalty card for an imported balance."""
        self.ensure_one()
        card = self._lpm_get_primary_loyalty_card()
        if card:
            return card

        if float_is_zero(target_points, precision_digits=6):
            _logger.info(
                "[loyalty_import_export] no card created for zero balance | partner_id=%s | partner=%r",
                self.id, self.display_name,
            )
            return self.env['loyalty.card'].sudo()

        program = self._lpm_get_primary_loyalty_program()
        if not program:
            _logger.error(
                "[loyalty_import_export] import failed: no active loyalty program | partner_id=%s | target_points=%s",
                self.id, target_points,
            )
            raise UserError(_('No active loyalty program found. Create a loyalty program before importing balances.'))

        card = self.env['loyalty.card'].sudo().create({
            'partner_id': self.id,
            'program_id': program.id,
            'points': 0.0,
        })
        _logger.info(
            "[loyalty_import_export] created loyalty card from import | partner_id=%s | card_id=%s | program_id=%s",
            self.id, card.id, program.id,
        )
        return card

    @api.depends_context('uid')
    def _compute_loyalty_balance_points(self):
        for partner in self:
            card = partner._lpm_get_primary_loyalty_card() if partner.id else False
            partner.loyalty_balance_points = card.points if card else 0.0
            _logger.debug(
                "[loyalty_import_export] compute balance | partner_id=%s | card_id=%s | balance=%s | user=%s",
                partner.id,
                card.id if card else False,
                partner.loyalty_balance_points,
                self.env.user.login,
            )

    def _inverse_loyalty_balance_points(self):
        for partner in self:
            new_balance = float(partner.loyalty_balance_points or 0.0)
            if new_balance < 0:
                _logger.warning(
                    "[loyalty_import_export] rejected negative balance | partner_id=%s | value=%s | user=%s",
                    partner.id, new_balance, self.env.user.login,
                )
                raise UserError(_('Loyalty Balance Points cannot be negative.'))

            card = partner._lpm_get_or_create_primary_loyalty_card(new_balance)
            if not card:
                continue

            old_balance = float(card.points or 0.0)
            if float_compare(old_balance, new_balance, precision_digits=6) == 0:
                _logger.info(
                    "[loyalty_import_export] import no-op | partner_id=%s | card_id=%s | balance=%s | user=%s",
                    partner.id, card.id, old_balance, self.env.user.login,
                )
                continue

            difference = new_balance - old_balance
            card.write({'points': new_balance})
            partner._lpm_create_import_loyalty_history(card, old_balance, new_balance, difference)

            _logger.info(
                "[loyalty_import_export] imported balance | partner_id=%s | partner=%r | card_id=%s"
                " | old=%s | new=%s | diff=%s | user=%s | import_file=%s",
                partner.id, partner.display_name, card.id,
                old_balance, new_balance, difference,
                self.env.user.login, bool(self.env.context.get('import_file')),
            )

    def _lpm_create_import_loyalty_history(self, card, old_balance, new_balance, difference):
        self.ensure_one()
        used = abs(difference) if difference < 0 else 0.0
        issued = difference if difference > 0 else 0.0

        history = self.env['loyalty.history'].sudo().create({
            'card_id': card.id,
            'description': _('Imported customer loyalty balance: %.2f -> %.2f') % (
                old_balance, new_balance,
            ),
            'used': used,
            'issued': issued,
            'order_model': self._name,
            'order_id': self.id,
        })
        _logger.debug(
            "[loyalty_import_export] history created | history_id=%s | partner_id=%s | card_id=%s"
            " | issued=%s | used=%s",
            history.id, self.id, card.id, issued, used,
        )
