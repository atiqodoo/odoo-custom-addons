# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class ProductProductMistakeMapping(models.Model):
    _inherit = 'product.product'

    tinted_mistake_actual_ids = fields.One2many(
        'paint.tinting.mistake',
        'actual_product_id',
        string='Mistake Mappings',
    )
    tinted_mistake_intended_ids = fields.One2many(
        'paint.tinting.mistake',
        'intended_product_id',
        string='Intended Mistake References',
    )
    has_tinted_mistake_mapping = fields.Boolean(
        string='Mistaken Tint Mapped',
        compute='_compute_tinted_mistake_summary',
        store=True,
        index=True,
    )
    tinted_mistake_mapping_count = fields.Integer(
        string='Mistake Mappings',
        compute='_compute_tinted_mistake_summary',
        store=True,
    )
    tinted_mistake_open_count = fields.Integer(
        string='Open Mistake Mappings',
        compute='_compute_tinted_mistake_summary',
        store=True,
    )
    tinted_mistake_latest_id = fields.Many2one(
        'paint.tinting.mistake',
        string='Latest Mistake Mapping',
        compute='_compute_tinted_mistake_summary',
        store=True,
        index=True,
    )
    tinted_mistake_state = fields.Selection(
        related='tinted_mistake_latest_id.state',
        string='Mistake Status',
        store=True,
        readonly=True,
        index=True,
    )
    tinted_mistake_mismatch_type = fields.Selection(
        related='tinted_mistake_latest_id.mismatch_type',
        string='Mistake Mismatch Type',
        store=True,
        readonly=True,
        index=True,
    )
    tinted_mistake_stock_decision = fields.Selection(
        related='tinted_mistake_latest_id.stock_decision',
        string='Mistake Stock Decision',
        store=True,
        readonly=True,
        index=True,
    )
    tinted_mistake_financial_decision = fields.Selection(
        related='tinted_mistake_latest_id.financial_decision',
        string='Mistake Financial Decision',
        store=True,
        readonly=True,
        index=True,
    )

    @api.depends(
        'tinted_mistake_actual_ids.state',
        'tinted_mistake_actual_ids.mistake_date',
        'tinted_mistake_actual_ids.mismatch_type',
        'tinted_mistake_actual_ids.stock_decision',
        'tinted_mistake_actual_ids.financial_decision',
    )
    def _compute_tinted_mistake_summary(self):
        terminal_states = {'cancelled'}
        open_states = {'draft', 'under_review', 'confirmed', 'quarantined', 'resolved'}
        for product in self:
            mappings = product.tinted_mistake_actual_ids.filtered(
                lambda item: item.state not in terminal_states
            )
            open_mappings = mappings.filtered(lambda item: item.state in open_states)
            latest = mappings.sorted(
                key=lambda item: (
                    item.mistake_date
                    or item.create_date
                    or fields.Datetime.to_datetime('1970-01-01 00:00:00'),
                    item.id,
                ),
                reverse=True,
            )[:1]
            product.has_tinted_mistake_mapping = bool(mappings)
            product.tinted_mistake_mapping_count = len(mappings)
            product.tinted_mistake_open_count = len(open_mappings)
            product.tinted_mistake_latest_id = latest
            if mappings:
                _logger.debug(
                    '[PAINT_TINTING][MISTAKE][PRODUCT_SUMMARY] product_id=%s '
                    'mapped=%s open=%s latest_id=%s latest_state=%s',
                    product.id,
                    len(mappings),
                    len(open_mappings),
                    latest.id if latest else False,
                    latest.state if latest else False,
                )

    def action_view_tinted_mistake_mappings(self):
        self.ensure_one()
        action = self.env.ref('paint_tinting.action_tinted_mistakes').read()[0]
        action['domain'] = [('actual_product_id', '=', self.id), ('state', '!=', 'cancelled')]
        action['context'] = {
            'default_actual_product_id': self.id,
            'default_actual_uom_id': self.uom_id.id,
            'search_default_active_cases': 1,
        }
        return action
