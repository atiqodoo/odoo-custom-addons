import logging
import math

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


PROMOTION_PROFILES = [
    ('generic', 'Generic Promotion'),
    ('gamma_paints', 'Gamma Paints'),
    ('crown_paints', 'Crown Paints'),
    ('plascon', 'Plascon'),
    ('basco_paints', 'Basco Paints'),
]


class VendorPurchasePromotion(models.Model):
    _name = 'vendor.purchase.promotion'
    _description = 'Vendor Purchase Promotion Rule'
    _order = 'priority desc, product_id desc, min_charged_qty desc, id desc'

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        required=True,
        domain=[('supplier_rank', '>', 0)],
        index=True,
        ondelete='cascade',
    )
    calculation_profile = fields.Selection(
        PROMOTION_PROFILES,
        required=True,
        default='generic',
        index=True,
    )
    # Kept for backward compatibility with rules created by version 1.0.
    # New rules use product_tmpl_ids so one promotion can cover many products.
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Legacy Product',
        index=True,
        ondelete='cascade',
    )
    product_tmpl_ids = fields.Many2many(
        'product.template',
        'vendor_purchase_promotion_product_tmpl_rel',
        'promotion_id',
        'product_tmpl_id',
        string='Products',
        required=True,
        help='All products that use this promotion rule.',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        index=True,
        ondelete='cascade',
    )
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    min_charged_qty = fields.Float(required=True, default=1.0)
    max_charged_qty = fields.Float(help='Zero means no maximum quantity.')
    buy_qty = fields.Float(string='Buy Quantity', required=True, default=1.0)
    free_qty = fields.Float(string='FOC Quantity', required=True, default=0.0)
    repeat_offer = fields.Boolean(
        default=True,
        help='Repeat the free quantity for every complete multiple of Buy Quantity.',
    )
    override_discount = fields.Boolean(
        help='Use this discount instead of the purchase/vendor default.',
    )
    discount_percentage = fields.Float(string='Discount %')
    default_tint_type = fields.Selection(
        [
            ('not_tinted', 'Not Tinted'),
            ('factory', 'Factory'),
            ('showroom_branch', 'Showroom/Branch'),
            ('custom', 'Custom'),
        ],
        default='not_tinted',
    )
    default_tint_percentage = fields.Float(string='Default Tint %')
    priority = fields.Integer(default=10)
    notes = fields.Text()

    _sql_constraints = [
        (
            'promotion_nonnegative_quantities',
            'CHECK(min_charged_qty >= 0 AND max_charged_qty >= 0 AND buy_qty > 0 AND free_qty >= 0)',
            'Promotion quantities must be non-negative and Buy Quantity must be greater than zero.',
        ),
        (
            'promotion_discount_range',
            'CHECK(discount_percentage >= 0 AND discount_percentage <= 100)',
            'Promotion discount must be between 0 and 100 percent.',
        ),
        (
            'promotion_tint_nonnegative',
            'CHECK(default_tint_percentage >= 0)',
            'Tint percentage cannot be negative.',
        ),
    ]

    def init(self):
        """Populate the multi-product field from pre-1.1 single-product rules."""
        self.env.cr.execute("""
            INSERT INTO vendor_purchase_promotion_product_tmpl_rel
                (promotion_id, product_tmpl_id)
            SELECT rule.id, rule.product_tmpl_id
              FROM vendor_purchase_promotion rule
             WHERE rule.product_tmpl_id IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM vendor_purchase_promotion_product_tmpl_rel rel
                     WHERE rel.promotion_id = rule.id
                       AND rel.product_tmpl_id = rule.product_tmpl_id
               )
        """)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            legacy_product = values.get('product_tmpl_id')
            if legacy_product and not values.get('product_tmpl_ids'):
                values['product_tmpl_ids'] = [(6, 0, [legacy_product])]
        rules = super().create(vals_list)
        _logger.info(
            '[VPP_RULE] created rule_ids=%s product_counts=%s',
            rules.ids,
            {rule.id: len(rule.product_tmpl_ids) for rule in rules},
        )
        return rules

    @api.constrains('product_id', 'product_tmpl_id', 'product_tmpl_ids')
    def _check_product_variant(self):
        for rule in self:
            templates = rule.product_tmpl_ids | rule.product_tmpl_id
            if not templates:
                raise ValidationError(_('Select at least one product for the promotion.'))
            if rule.product_id and rule.product_id.product_tmpl_id not in templates:
                raise ValidationError(_('The selected variant does not belong to the selected products.'))

    @api.constrains('min_charged_qty', 'max_charged_qty', 'date_start', 'date_end')
    def _check_ranges(self):
        for rule in self:
            if rule.max_charged_qty and rule.min_charged_qty > rule.max_charged_qty:
                raise ValidationError(_('Minimum charged quantity cannot exceed maximum charged quantity.'))
            if rule.date_start and rule.date_end and rule.date_start > rule.date_end:
                raise ValidationError(_('Promotion start date cannot be after its end date.'))

    @api.onchange('default_tint_type')
    def _onchange_default_tint_type(self):
        rates = {'not_tinted': 0.0, 'factory': 7.0, 'showroom_branch': 15.0}
        if self.default_tint_type in rates:
            self.default_tint_percentage = rates[self.default_tint_type]

    def calculate_foc_qty(self, charged_qty):
        self.ensure_one()
        charged_qty = float(charged_qty or 0.0)
        if charged_qty < self.min_charged_qty:
            return 0.0
        if self.max_charged_qty and charged_qty > self.max_charged_qty:
            return 0.0
        if self.repeat_offer:
            multiples = math.floor(charged_qty / self.buy_qty)
            return multiples * self.free_qty
        return self.free_qty if charged_qty >= self.buy_qty else 0.0

    @api.model
    def resolve_rule(self, order, product, charged_qty, on_date=None):
        if not order or not order.partner_id or not product:
            return self.browse()
        on_date = on_date or fields.Date.context_today(self)
        commercial_vendor = order.partner_id.commercial_partner_id
        domain = [
            ('active', '=', True),
            ('company_id', '=', order.company_id.id),
            ('partner_id', 'in', [order.partner_id.id, commercial_vendor.id]),
            '|',
            ('product_tmpl_ids', 'in', [product.product_tmpl_id.id]),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            '|', ('product_id', '=', product.id), ('product_id', '=', False),
            ('min_charged_qty', '<=', charged_qty),
            '|', ('max_charged_qty', '=', 0), ('max_charged_qty', '>=', charged_qty),
            '|', ('date_start', '=', False), ('date_start', '<=', on_date),
            '|', ('date_end', '=', False), ('date_end', '>=', on_date),
        ]
        rules = self.search(domain, order=self._order, limit=2)
        if len(rules) > 1:
            _logger.warning(
                '[VPP_RULE] ambiguous_rules order_id=%s product_id=%s charged_qty=%s rule_ids=%s selected=%s',
                order.id,
                product.id,
                charged_qty,
                rules.ids,
                rules[0].id,
            )
        rule = rules[:1]
        _logger.info(
            '[VPP_RULE] resolved order_id=%s vendor_id=%s product_id=%s charged_qty=%s '
            'rule_id=%s profile=%s rule_product_ids=%s',
            order.id,
            order.partner_id.id,
            product.id,
            charged_qty,
            rule.id if rule else False,
            rule.calculation_profile if rule else False,
            rule.product_tmpl_ids.ids if rule else [],
        )
        return rule


class VendorPurchasePromotionApplication(models.Model):
    _name = 'vendor.purchase.promotion.application'
    _description = 'Applied Vendor Purchase Promotion'
    _order = 'id desc'

    name = fields.Char(required=True, default='New', copy=False, index=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    partner_id = fields.Many2one('res.partner', required=True, index=True)
    promotion_id = fields.Many2one('vendor.purchase.promotion', required=True, ondelete='restrict')
    purchase_id = fields.Many2one('purchase.order', required=True, index=True, ondelete='cascade')
    charged_line_id = fields.Many2one('purchase.order.line', required=True, index=True, ondelete='cascade')
    foc_line_id = fields.Many2one('purchase.order.line', required=True, index=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True, index=True)
    charged_qty = fields.Float(required=True)
    promised_foc_qty = fields.Float(required=True)
    received_foc_qty = fields.Float(
        compute='_compute_foc_status',
        store=True,
        readonly=True,
    )
    outstanding_foc_qty = fields.Float(
        compute='_compute_foc_status',
        store=True,
        readonly=True,
    )
    fulfillment_state = fields.Selection(
        [
            ('awaiting', 'Awaiting FOC'),
            ('partial', 'Partially Received'),
            ('fulfilled', 'Fulfilled'),
            ('cancelled', 'Backorder Cancelled'),
        ],
        compute='_compute_foc_status',
        store=True,
        readonly=True,
    )
    promotion_snapshot = fields.Json(readonly=True)
    bill_ids = fields.Many2many(
        'account.move',
        'vendor_promotion_application_bill_rel',
        'application_id',
        'bill_id',
        string='Vendor Bills',
        readonly=True,
    )

    _sql_constraints = [
        (
            'unique_charged_line_application',
            'UNIQUE(charged_line_id)',
            'A charged purchase line can only have one promotion application.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'vendor.purchase.promotion.application'
                ) or 'New'
        records = super().create(vals_list)
        for record in records:
            _logger.info(
                '[VPP_APPLICATION] created application_id=%s po_id=%s charged_line_id=%s '
                'foc_line_id=%s charged_qty=%s promised_foc=%s promotion_id=%s',
                record.id,
                record.purchase_id.id,
                record.charged_line_id.id,
                record.foc_line_id.id,
                record.charged_qty,
                record.promised_foc_qty,
                record.promotion_id.id,
            )
        return records

    @api.depends(
        'promised_foc_qty',
        'foc_line_id.qty_received',
        'foc_line_id.move_ids.state',
    )
    def _compute_foc_status(self):
        for application in self:
            received = application.foc_line_id.qty_received or 0.0
            outstanding = max((application.promised_foc_qty or 0.0) - received, 0.0)
            moves = application.foc_line_id.move_ids
            cancelled = bool(moves) and all(move.state == 'cancel' for move in moves)
            if outstanding <= 0:
                state = 'fulfilled'
            elif cancelled:
                state = 'cancelled'
            elif received > 0:
                state = 'partial'
            else:
                state = 'awaiting'
            application.received_foc_qty = received
            application.outstanding_foc_qty = outstanding
            application.fulfillment_state = state
            _logger.debug(
                '[VPP_FOC] status application_id=%s expected=%s received=%s outstanding=%s state=%s',
                application.id,
                application.promised_foc_qty,
                received,
                outstanding,
                state,
            )
