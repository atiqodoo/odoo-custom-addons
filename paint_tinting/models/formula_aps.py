# -*- coding: utf-8 -*-
"""Customer-specific As Per Sample (APS) metadata and creation service."""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class TintingFormulaVersionAps(models.Model):
    _inherit = 'tinting.formula.version'

    origin = fields.Selection(
        selection_add=[('aps', 'As Per Sample')],
        ondelete={'aps': 'set default'},
    )
    is_aps = fields.Boolean(
        string='APS (As Per Sample)', index=True, tracking=True, copy=False,
        help='This approved formula version was captured for a specific customer sample.',
    )
    aps_customer_id = fields.Many2one(
        'res.partner', string='APS Customer', index=True, tracking=True, copy=False,
        ondelete='restrict',
        help='Customer whose physical sample this formula version matches.',
    )

    @api.constrains('is_aps', 'aps_customer_id', 'state')
    def _check_aps_customer(self):
        for version in self:
            if version.is_aps and not version.aps_customer_id:
                raise ValidationError(_('An APS formula version must have a customer.'))
            if version.aps_customer_id and not version.is_aps:
                raise ValidationError(_('APS Customer can only be set on an APS formula version.'))
            if version.is_aps and version.state != 'approved':
                raise ValidationError(_('APS formula versions must be Approved.'))

    @api.model
    def create_aps_from_recipe(self, family, recipe, customer, previous_version=None,
                               change_summary=None):
        """Create one audited, auto-approved APS version without changing the default."""
        family.ensure_one()
        customer.ensure_one()
        operator = self.env.user
        service = self.env['tinting.formula.recipe.service'].sudo()
        normalized = service.normalize_recipe(recipe)
        signature = service.signature(normalized)
        family_sudo = family.sudo()

        _logger.info(
            "FORMULA_APS_CREATE_START family_id=%s customer_id=%s previous_version_id=%s "
            "operator_id=%s recipe=%s signature=%s",
            family.id, customer.id, previous_version.id if previous_version else False,
            operator.id, normalized, signature,
        )

        duplicate = family_sudo.version_ids.filtered(
            lambda item: item.recipe_signature == signature
        )[:1]
        if duplicate:
            _logger.warning(
                "FORMULA_APS_CREATE_DUPLICATE_BLOCKED family_id=%s customer_id=%s "
                "existing_version_id=%s existing_is_aps=%s signature=%s",
                family.id, customer.id, duplicate.id, duplicate.is_aps, signature,
            )
            raise ValidationError(_(
                'This exact recipe already exists as %(version)s. Select that existing '
                'version instead of creating a duplicate APS version.',
                version=duplicate.display_name,
            ))

        version = self.sudo().create_from_recipe(
            family=family_sudo,
            recipe=normalized,
            state='approved',
            origin='aps',
            previous_version=previous_version.sudo() if previous_version else None,
            notes=_('Automatically approved as APS for customer %(customer)s.',
                    customer=customer.display_name),
            change_reason=_('As Per Sample recipe for %(customer)s',
                            customer=customer.display_name),
        )
        now = fields.Datetime.now()
        version.sudo().with_context(allow_formula_system_write=True).write({
            'is_aps': True,
            'aps_customer_id': customer.id,
            'created_by_id': operator.id,
            'approved_by_id': operator.id,
            'approved_date': now,
        })
        family_sudo.with_context(allow_formula_system_write=True).write({'state': 'approved'})
        version.sudo().message_post(body=_(
            'APS formula automatically approved for customer %(customer)s by %(user)s. '
            'It was not made the general default formula. Changes: %(changes)s',
            customer=customer.display_name,
            user=operator.display_name,
            changes=change_summary or version.change_summary,
        ))
        _logger.info(
            "FORMULA_APS_CREATE_DONE family_id=%s version_id=%s version_number=%s "
            "customer_id=%s operator_id=%s default_version_id=%s signature=%s",
            family.id, version.id, version.version_number, customer.id, operator.id,
            family_sudo.default_version_id.id, signature,
        )
        return version
