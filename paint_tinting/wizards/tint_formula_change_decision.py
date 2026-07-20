# -*- coding: utf-8 -*-
"""Intercept changed tint recipes and classify them as APS or Updated Formula."""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class TintFormulaChangeDecision(models.TransientModel):
    _name = 'tint.formula.change.decision'
    _description = 'Tint Formula Change Decision'

    tint_wizard_id = fields.Many2one(
        'tint.wizard', required=True, readonly=True, ondelete='cascade',
    )
    baseline_version_id = fields.Many2one(
        'tinting.formula.version', string='Compared Formula Version', readonly=True,
    )
    aps_selected = fields.Boolean(string='APS (As Per Sample)', default=True)
    updated_formula_selected = fields.Boolean(string='Updated Formula', default=False)
    customer_id = fields.Many2one(
        'res.partner', string='Customer',
        help='Search for an existing customer or create a new customer.',
    )
    change_summary = fields.Text(readonly=True)
    requested_recipe_json = fields.Text(readonly=True)
    requested_signature = fields.Char(readonly=True)
    continuation = fields.Selection([
        ('create_product', 'Create Tinted Product & MO'),
        ('compare_cost', 'Compare Costs Across Brands'),
    ], default='create_product', required=True, readonly=True)

    @api.onchange('aps_selected')
    def _onchange_aps_selected(self):
        if self.aps_selected:
            self.updated_formula_selected = False
        elif not self.updated_formula_selected:
            self.updated_formula_selected = True
            self.customer_id = False

    @api.onchange('updated_formula_selected')
    def _onchange_updated_formula_selected(self):
        if self.updated_formula_selected:
            self.aps_selected = False
            self.customer_id = False
        elif not self.aps_selected:
            self.aps_selected = True

    @api.constrains('aps_selected', 'updated_formula_selected')
    def _check_decision(self):
        for decision in self:
            if decision.aps_selected == decision.updated_formula_selected:
                raise ValidationError(_('Select exactly one option: APS or Updated Formula.'))

    def action_confirm(self):
        self.ensure_one()
        if self.aps_selected and not self.customer_id:
            _logger.warning(
                "TINT_FORMULA_DECISION_CUSTOMER_REQUIRED decision_id=%s tint_wizard_id=%s "
                "user_id=%s",
                self.id, self.tint_wizard_id.id, self.env.user.id,
            )
            raise ValidationError(_('Customer is required when APS is selected.'))
        wizard = self.tint_wizard_id.exists()
        if not wizard:
            raise ValidationError(_('The original Tinting Wizard has expired. Please start again.'))

        service = self.env['tinting.formula.recipe.service']
        current_recipe = wizard._get_current_tint_recipe()
        current_signature = service.signature(current_recipe)
        _logger.info(
            "TINT_FORMULA_DECISION_CONFIRM decision_id=%s tint_wizard_id=%s mode=%s "
            "customer_id=%s baseline_version_id=%s stored_signature=%s current_signature=%s",
            self.id, wizard.id, 'aps' if self.aps_selected else 'updated',
            self.customer_id.id, self.baseline_version_id.id,
            self.requested_signature, current_signature,
        )
        if current_signature != self.requested_signature:
            _logger.error(
                "TINT_FORMULA_DECISION_RECIPE_DRIFT decision_id=%s tint_wizard_id=%s "
                "stored_recipe=%s current_recipe=%s",
                self.id, wizard.id, self.requested_recipe_json, current_recipe,
            )
            raise ValidationError(_(
                'The tint recipe changed after this decision popup opened. Close it and '
                'start the requested action again.'
            ))

        if self.aps_selected:
            family = self.baseline_version_id.formula_id
            version = self.env['tinting.formula.version'].create_aps_from_recipe(
                family=family,
                recipe=current_recipe,
                customer=self.customer_id,
                previous_version=self.baseline_version_id,
                change_summary=self.change_summary,
            )
            wizard.write({
                'formula_id': family.id,
                'formula_version_id': version.id,
                'formula_applied': True,
            })
            _logger.info(
                "TINT_FORMULA_DECISION_APS_ATTACHED decision_id=%s tint_wizard_id=%s "
                "version_id=%s customer_id=%s",
                self.id, wizard.id, version.id, self.customer_id.id,
            )

        continuation = self.continuation or 'create_product'
        continued_wizard = wizard.with_context(
            skip_tint_formula_change_decision=True,
            tint_formula_decision='aps' if self.aps_selected else 'updated',
            tint_formula_continuation=continuation,
        )
        if continuation == 'compare_cost':
            result = continued_wizard.action_open_cost_comparison()
        else:
            result = continued_wizard.action_create_tinted_product()
        _logger.info(
            "TINT_FORMULA_DECISION_CONTINUE decision_id=%s tint_wizard_id=%s mode=%s "
            "continuation=%s result_model=%s result_res_id=%s",
            self.id, wizard.id, 'aps' if self.aps_selected else 'updated',
            continuation,
            result.get('res_model') if isinstance(result, dict) else False,
            result.get('res_id') if isinstance(result, dict) else False,
        )
        return result


class TintWizardFormulaChangeIntercept(models.TransientModel):
    _inherit = 'tint.wizard'

    selected_formula_is_aps = fields.Boolean(
        related='formula_version_id.is_aps', string='APS Formula', readonly=True,
    )
    selected_formula_aps_customer_id = fields.Many2one(
        related='formula_version_id.aps_customer_id',
        string='APS Customer', readonly=True,
    )

    def _get_current_tint_recipe(self):
        self.ensure_one()
        service = self.env['tinting.formula.recipe.service']
        recipe = {
            line.colorant_code: line.shots
            for line in self.colorant_line_ids
            if line.colorant_code and line.colorant_id and line.shots > 0
        }
        normalized = service.normalize_recipe(recipe)
        _logger.debug(
            "TINT_FORMULA_CURRENT_RECIPE tint_wizard_id=%s formula_id=%s "
            "formula_version_id=%s recipe=%s",
            self.id, self.formula_id.id, self.formula_version_id.id, normalized,
        )
        return normalized

    def _get_tint_formula_family(self):
        self.ensure_one()
        if self.formula_id:
            return self.formula_id
        if not self.base_variant_id or not self.colour_code_id:
            return self.env['tinting.formula']
        service = self.env['tinting.formula.recipe.service'].sudo()
        attribute_value = self.base_variant_id.product_template_attribute_value_ids[:1]
        attribute_name = service.normalize_attribute(attribute_value.name if attribute_value else '')
        return service.find_family(
            self.colour_code_id,
            self.base_variant_id.categ_id,
            self.base_variant_id.uom_id,
            attribute_name,
        )

    def _get_tint_formula_baseline(self):
        self.ensure_one()
        if self.formula_version_id:
            return self.formula_version_id
        family = self._get_tint_formula_family()
        if not family:
            return self.env['tinting.formula.version']
        available = family.sudo().version_ids.filtered(
            lambda version: version.active and version.state in ('approved', 'superseded')
        )
        if family.default_version_id in available:
            return family.default_version_id
        standard = available.filtered(lambda version: not version.is_aps).sorted(
            key=lambda version: version.version_number, reverse=True,
        )
        return standard[:1] or available.sorted(
            key=lambda version: version.version_number, reverse=True,
        )[:1]

    def _format_tint_recipe_changes(self, changes):
        lines = []
        for change in changes:
            if change['type'] == 'added':
                lines.append(_('%(code)s added: %(new).2f shots', **change))
            elif change['type'] == 'removed':
                lines.append(_('%(code)s removed: %(old).2f shots', **change))
            else:
                lines.append(_(
                    '%(code)s changed: %(old).2f -> %(new).2f shots', **change,
                ))
        return '\n'.join(lines)

    def _validate_selling_price_before_formula_decision(self):
        """Run the existing price gates before opening the change popup."""
        self.ensure_one()
        _logger.info(
            "TINT_FORMULA_PRECHECK_PRICE tint_wizard_id=%s selling_price=%s "
            "total_cost=%s user_id=%s",
            self.id, self.selling_price_incl_vat, self.total_cost_incl_vat,
            self.env.user.id,
        )
        if not self.selling_price_incl_vat or self.selling_price_incl_vat <= 0:
            _logger.warning(
                "TINT_FORMULA_PRECHECK_PRICE_BLOCKED tint_wizard_id=%s reason=missing_or_zero "
                "selling_price=%s total_cost=%s user_id=%s",
                self.id, self.selling_price_incl_vat, self.total_cost_incl_vat,
                self.env.user.id,
            )
            raise ValidationError(_(
                'Selling price must be greater than zero.\n'
                'Please check the Cost Summary tab.'
            ))
        if self.selling_price_incl_vat < self.total_cost_incl_vat:
            shortage = self.total_cost_incl_vat - self.selling_price_incl_vat
            _logger.warning(
                "TINT_FORMULA_PRECHECK_PRICE_BLOCKED tint_wizard_id=%s reason=below_cost "
                "selling_price=%s total_cost=%s shortage=%s user_id=%s",
                self.id, self.selling_price_incl_vat, self.total_cost_incl_vat,
                shortage, self.env.user.id,
            )
            raise ValidationError(_(
                "Cannot create tinted product — selling price is below cost!\n\n"
                "Selling Price:  %(price)s KES\n"
                "Total Cost:     %(cost)s KES\n"
                "Shortfall:      %(short)s KES\n\n"
                "Please increase the selling price in the Cost Summary tab "
                "to at least %(cost)s KES before proceeding.",
                price=f"{self.selling_price_incl_vat:.2f}",
                cost=f"{self.total_cost_incl_vat:.2f}",
                short=f"{shortage:.2f}",
            ))
        _logger.info(
            "TINT_FORMULA_PRECHECK_PRICE_PASSED tint_wizard_id=%s selling_price=%s "
            "total_cost=%s",
            self.id, self.selling_price_incl_vat, self.total_cost_incl_vat,
        )
        return True

    def _get_formula_change_decision_action(self, continuation='create_product'):
        """Return a decision popup action when the current recipe is genuinely new."""
        self.ensure_one()
        recipe = self._get_current_tint_recipe()
        baseline = self._get_tint_formula_baseline()
        if not recipe or not baseline:
            _logger.info(
                "TINT_FORMULA_CHANGE_CHECK_SKIPPED tint_wizard_id=%s reason=%s "
                "continuation=%s recipe=%s baseline_version_id=%s",
                self.id, 'empty_recipe' if not recipe else 'no_approved_baseline',
                continuation, recipe, baseline.id,
            )
            return False

        service = self.env['tinting.formula.recipe.service']
        baseline_recipe = baseline.get_shots_dict()
        requested_signature = service.signature(recipe)
        baseline_signature = service.signature(baseline_recipe)
        if requested_signature == baseline_signature:
            _logger.info(
                "TINT_FORMULA_CHANGE_CHECK_UNCHANGED tint_wizard_id=%s "
                "baseline_version_id=%s continuation=%s signature=%s",
                self.id, baseline.id, continuation, requested_signature,
            )
            return False

        existing = baseline.formula_id.sudo().version_ids.filtered(
            lambda version: version.active
            and version.state in ('approved', 'superseded')
            and version.recipe_signature == requested_signature
        )[:1]
        if existing:
            self.write({
                'formula_id': existing.formula_id.id,
                'formula_version_id': existing.id,
                'formula_applied': True,
            })
            _logger.info(
                "TINT_FORMULA_CHANGE_MATCHED_EXISTING tint_wizard_id=%s "
                "baseline_version_id=%s matched_version_id=%s continuation=%s signature=%s",
                self.id, baseline.id, existing.id, continuation, requested_signature,
            )
            return False

        changes = service.diff(baseline_recipe, recipe)
        summary = self._format_tint_recipe_changes(changes)
        decision = self.env['tint.formula.change.decision'].create({
            'tint_wizard_id': self.id,
            'baseline_version_id': baseline.id,
            'aps_selected': True,
            'updated_formula_selected': False,
            'change_summary': summary,
            'requested_recipe_json': json.dumps(recipe, sort_keys=True),
            'requested_signature': requested_signature,
            'continuation': continuation,
        })
        _logger.warning(
            "TINT_FORMULA_CHANGE_DETECTED tint_wizard_id=%s decision_id=%s "
            "family_id=%s baseline_version_id=%s baseline_recipe=%s requested_recipe=%s "
            "continuation=%s changes=%s user_id=%s",
            self.id, decision.id, baseline.formula_id.id, baseline.id,
            baseline_recipe, recipe, continuation, changes, self.env.user.id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Formula Change Detected'),
            'res_model': 'tint.formula.change.decision',
            'res_id': decision.id,
            'view_mode': 'form',
            'view_id': self.env.ref('paint_tinting.view_tint_formula_change_decision_form').id,
            'target': 'new',
        }

    def action_create_tinted_product(self):
        self.ensure_one()
        self._validate_selling_price_before_formula_decision()
        if self.env.context.get('skip_tint_formula_change_decision'):
            _logger.info(
                "TINT_FORMULA_DECISION_BYPASS tint_wizard_id=%s mode=%s continuation=%s",
                self.id, self.env.context.get('tint_formula_decision'),
                self.env.context.get('tint_formula_continuation'),
            )
            return super().action_create_tinted_product()
        decision_action = self._get_formula_change_decision_action('create_product')
        return decision_action or super().action_create_tinted_product()

    def action_open_cost_comparison(self):
        self.ensure_one()
        if self.env.context.get('skip_tint_formula_change_decision'):
            _logger.info(
                "TINT_FORMULA_COMPARE_DECISION_BYPASS tint_wizard_id=%s mode=%s",
                self.id, self.env.context.get('tint_formula_decision'),
            )
            return super().action_open_cost_comparison()
        decision_action = self._get_formula_change_decision_action('compare_cost')
        if decision_action:
            _logger.info(
                "TINT_FORMULA_COMPARE_DECISION_OPEN tint_wizard_id=%s decision_id=%s",
                self.id, decision_action.get('res_id'),
            )
            return decision_action
        return super().action_open_cost_comparison()
