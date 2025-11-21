# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # --------------------------------------------------------------------- #
    # FIELDS
    # --------------------------------------------------------------------- #
    user_has_vendor_override = fields.Boolean(
        string="Vendor Override",
        compute='_compute_user_has_vendor_override',
        store=False,
    )

    # --------------------------------------------------------------------- #
    # COMPUTED FIELDS
    # --------------------------------------------------------------------- #
    @api.depends('user_id.groups_id')
    def _compute_user_has_vendor_override(self):
        override_group = self.env.ref('vendor_product_restriction.group_vendor_override', raise_if_not_found=False)
        for po in self:
            po.user_has_vendor_override = override_group and (override_group in self.env.user.groups_id)

    # --------------------------------------------------------------------- #
    # ONCHANGE: GRID VALIDATION (MATRIX) – FIXED & ROBUST
    # --------------------------------------------------------------------- #
    @api.onchange('grid', 'grid_update', 'partner_id')
    def _onchange_grid(self):
        """
        Validate grid changes:
        - Skip if override or no vendor
        - Resolve variant from ptav_ids via attribute-value mapping
        - Block if variant NOT mapped to vendor
        """
        if not self.grid_update or not self.partner_id or self.user_has_vendor_override:
            return

        try:
            grid_data = json.loads(self.grid)
            changes = grid_data.get('changes', [])
        except (json.JSONDecodeError, TypeError) as e:
            _logger.warning("Invalid grid JSON in PO %s: %s", self.id or 'New', e)
            return

        for change in changes:
            ptav_ids = change.get('ptav_ids')
            qty = change.get('qty', 0)
            tmpl_id = change.get('product_template_id')

            if not ptav_ids or qty <= 0 or not tmpl_id:
                continue

            template = self.env['product.template'].browse(tmpl_id)
            if not template.exists() or not template.attribute_line_ids:
                continue

            # === SAFELY RESOLVE VARIANT FROM PTAV IDS ===
            domain = [('product_tmpl_id', '=', tmpl_id)]
            for ptav_id in ptav_ids:
                domain.append(('product_template_attribute_value_ids', '=', ptav_id))

            variant = self.env['product.product'].search(domain, limit=1)
            if not variant:
                _logger.debug(
                    "No variant found for template %s with ptav_ids %s — deferring validation",
                    tmpl_id, ptav_ids
                )
                continue  # Let Odoo create it later; will be caught on save

            # === VENDOR MAPPING CHECK ===
            if not variant.seller_ids.filtered(
                lambda s: s.partner_id == self.partner_id and s.product_id == variant
            ):
                raise UserError(_(
                    "Product variant '%s' is not supplied by vendor '%s'.\n"
                    "Only products explicitly mapped to this vendor are allowed.",
                    variant.display_name,
                    self.partner_id.display_name
                ))

            _logger.debug("Variant %s allowed for vendor %s", variant.id, self.partner_id.id)

    # --------------------------------------------------------------------- #
    # ONCHANGE: MANUAL LINES (NON-GRID)
    # --------------------------------------------------------------------- #
    @api.onchange('order_line')
    def _onchange_order_line(self):
        if self.user_has_vendor_override or not self.partner_id:
            return

        for line in self.order_line:
            if not line.product_id or line.display_type:
                continue

            if not line.product_id.seller_ids.filtered(
                lambda s: s.partner_id == self.partner_id and s.product_id == line.product_id
            ):
                raise UserError(_(
                    "Product '%s' is not available from vendor '%s'.\n"
                    "You can only add products mapped to the selected vendor.",
                    line.product_id.display_name,
                    self.partner_id.display_name
                ))

    # --------------------------------------------------------------------- #
    # CONSTRAINT: FINAL SAVE (REINFORCED)
    # --------------------------------------------------------------------- #
    @api.constrains('order_line', 'partner_id')
    def _check_vendor_restriction_on_save(self):
        for po in self:
            if po.user_has_vendor_override or not po.partner_id:
                continue

            for line in po.order_line:
                if not line.product_id or line.display_type:
                    continue

                if not line.product_id.seller_ids.filtered(
                    lambda s: s.partner_id == po.partner_id and s.product_id == line.product_id
                ):
                    raise UserError(_(
                        "Cannot save Purchase Order.\n"
                        "Product '%s' is not supplied by '%s'.\n"
                        "Remove or correct invalid lines.",
                        line.product_id.display_name,
                        po.partner_id.display_name
                    ))

    # --------------------------------------------------------------------- #
    # HELPER: VALIDATE GRID-GENERATED LINES ON SAVE
    # --------------------------------------------------------------------- #
    def _validate_grid_lines(self):
        """Re-validate all order lines (including grid-generated) against vendor mapping"""
        if not self.order_line or self.user_has_vendor_override or not self.partner_id:
            return

        self._check_vendor_restriction_on_save()

    # --------------------------------------------------------------------- #
    # OVERRIDE: CREATE / WRITE – ENSURE FINAL VALIDATION
    # --------------------------------------------------------------------- #
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.grid and not record.user_has_vendor_override and record.partner_id:
                record._validate_grid_lines()
        return records

    def write(self, vals):
        res = super().write(vals)
        trigger_fields = ('grid', 'grid_update', 'partner_id', 'order_line')
        if any(key in vals for key in trigger_fields):
            for record in self:
                if record.grid and not record.user_has_vendor_override and record.partner_id:
                    record._validate_grid_lines()
        return res