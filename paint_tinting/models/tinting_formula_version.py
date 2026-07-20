# -*- coding: utf-8 -*-
"""Immutable, auditable recipe versions for tinting formula families."""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


class TintingFormulaVersion(models.Model):
    _name = 'tinting.formula.version'
    _description = 'Tinting Formula Version'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'formula_id, version_number desc, id desc'
    _rec_name = 'name'

    formula_id = fields.Many2one(
        'tinting.formula', required=True, ondelete='cascade', index=True, tracking=True,
        string='Formula Family',
    )
    version_number = fields.Integer(required=True, readonly=True, index=True, tracking=True)
    name = fields.Char(compute='_compute_name', store=True)
    previous_version_id = fields.Many2one(
        'tinting.formula.version', ondelete='set null', readonly=True, copy=False,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Validated'),
        ('approved', 'Approved'),
        ('superseded', 'Superseded'),
    ], default='draft', required=True, index=True, tracking=True)
    origin = fields.Selection([
        ('manual', 'Manual'),
        ('mo', 'Manufacturing Order'),
        ('import', 'Spreadsheet Import'),
        ('migration', 'Legacy Migration'),
    ], default='manual', required=True, readonly=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    line_ids = fields.One2many(
        'tinting.formula.version.line', 'version_id', string='Colorant Shots', copy=True,
    )
    total_shots = fields.Float(compute='_compute_recipe', store=True, digits=(10, 2))
    total_ml = fields.Float(compute='_compute_recipe', store=True, digits=(10, 3))
    total_litres = fields.Float(compute='_compute_recipe', store=True, digits=(10, 6))
    recipe_signature = fields.Char(compute='_compute_recipe', store=True, index=True, copy=False)
    recipe_json = fields.Text(compute='_compute_recipe', store=True, copy=False)
    change_summary = fields.Text(compute='_compute_change_summary', store=True)
    change_reason = fields.Text(tracking=True)
    notes = fields.Text()
    source_mo_id = fields.Many2one('mrp.production', ondelete='set null', copy=False, readonly=True)
    source_bom_id = fields.Many2one('mrp.bom', ondelete='set null', copy=False, readonly=True)
    import_batch_id = fields.Many2one(
        'tinting.formula.import.batch', ondelete='set null', copy=False, readonly=True,
    )
    created_by_id = fields.Many2one(
        'res.users', default=lambda self: self.env.user, required=True, readonly=True,
    )
    created_date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    approved_date = fields.Datetime(readonly=True, copy=False)
    times_used = fields.Integer(default=0, readonly=True, copy=False)
    last_used_date = fields.Datetime(readonly=True, copy=False)
    is_default = fields.Boolean(compute='_compute_is_default')

    _sql_constraints = [
        ('formula_version_unique', 'unique(formula_id, version_number)',
         'A version number may only occur once within a formula family.'),
        ('version_number_positive', 'CHECK(version_number > 0)',
         'Formula version numbers must be greater than zero.'),
    ]

    @api.depends('formula_id.name', 'version_number')
    def _compute_name(self):
        for version in self:
            version.name = '%s / V%s' % (
                version.formula_id.name or _('New Formula'), version.version_number or '?',
            )

    @api.depends('formula_id.default_version_id')
    def _compute_is_default(self):
        for version in self:
            version.is_default = version.formula_id.default_version_id == version

    @api.depends('line_ids.colorant_code', 'line_ids.shots')
    def _compute_recipe(self):
        service = self.env['tinting.formula.recipe.service']
        for version in self:
            recipe = version.get_shots_dict()
            version.total_shots = sum(recipe.values())
            version.total_ml = version.total_shots * 0.616
            version.total_litres = version.total_ml / 1000.0
            version.recipe_json = json.dumps(recipe, sort_keys=True)
            version.recipe_signature = service.signature(recipe)
            _logger.debug(
                "FORMULA_VERSION_RECIPE_COMPUTED version_id=%s version=%s recipe=%s signature=%s",
                version.id, version.display_name, recipe, version.recipe_signature,
            )

    @api.depends(
        'recipe_signature', 'previous_version_id.recipe_signature',
        'previous_version_id.line_ids.colorant_code', 'previous_version_id.line_ids.shots',
    )
    def _compute_change_summary(self):
        service = self.env['tinting.formula.recipe.service']
        for version in self:
            previous_recipe = version.previous_version_id.get_shots_dict() if version.previous_version_id else {}
            changes = service.diff(previous_recipe, version.get_shots_dict())
            labels = []
            for change in changes:
                if change['type'] == 'added':
                    labels.append(_('%(code)s added: %(new).2f', **change))
                elif change['type'] == 'removed':
                    labels.append(_('%(code)s removed: %(old).2f', **change))
                else:
                    labels.append(_('%(code)s: %(old).2f → %(new).2f', **change))
            version.change_summary = '\n'.join(labels) or _('Initial recipe')

    @api.model_create_multi
    def create(self, vals_list):
        versions = super().create(vals_list)
        for version in versions:
            _logger.info(
                "FORMULA_VERSION_CREATED version_id=%s family_id=%s number=%s state=%s "
                "origin=%s creator_id=%s",
                version.id, version.formula_id.id, version.version_number, version.state,
                version.origin, self.env.user.id,
            )
        return versions

    def write(self, vals):
        protected = {'formula_id', 'version_number', 'line_ids'} & set(vals)
        if protected and not self.env.context.get('allow_formula_system_write'):
            locked = self.filtered(lambda version: version.state != 'draft')
            if locked:
                _logger.warning(
                    "FORMULA_VERSION_WRITE_BLOCKED ids=%s state=%s fields=%s user_id=%s",
                    locked.ids, locked.mapped('state'), sorted(protected), self.env.user.id,
                )
                raise UserError(_('Only Draft formula versions can have their recipe changed.'))
        result = super().write(vals)
        _logger.info(
            "FORMULA_VERSION_UPDATED ids=%s fields=%s user_id=%s",
            self.ids, sorted(vals), self.env.user.id,
        )
        return result

    def unlink(self):
        if not self.env.context.get('allow_formula_system_write') and self.filtered(
            lambda version: version.state != 'draft'
        ):
            raise UserError(_('Only Draft formula versions can be deleted.'))
        _logger.warning("FORMULA_VERSION_DELETE ids=%s user_id=%s", self.ids, self.env.user.id)
        return super().unlink()

    @api.model
    def _next_version_number(self, family):
        self.env.cr.execute('SELECT id FROM tinting_formula WHERE id = %s FOR UPDATE', [family.id])
        last = self.search([('formula_id', '=', family.id)], order='version_number desc', limit=1)
        number = (last.version_number or 0) + 1
        _logger.debug("FORMULA_VERSION_NEXT_NUMBER family_id=%s next=%s", family.id, number)
        return number

    @api.model
    def create_from_recipe(
        self, family, recipe, products=None, state='draft', origin='manual',
        previous_version=None, source_mo=None, source_bom=None, import_batch=None,
        notes=None, change_reason=None,
    ):
        family.ensure_one()
        service = self.env['tinting.formula.recipe.service']
        normalized = service.normalize_recipe(recipe)
        if not normalized:
            raise ValidationError(_('A formula version must contain at least one non-zero colorant.'))
        products = products or {}
        colorant_model = self.env['product.product']
        line_commands = []
        for sequence, (code, shots) in enumerate(normalized.items(), start=1):
            product = products.get(code)
            if not product:
                product = colorant_model.search([
                    ('product_tmpl_id.is_colorant', '=', True),
                    ('product_tmpl_id.colorant_code', '=ilike', code),
                ], limit=1)
            if not product:
                raise ValidationError(_('Colorant code %s is not mapped to a product.', code))
            line_commands.append((0, 0, {
                'colorant_id': product.id,
                'shots': shots,
                'sequence': int(code[1:]) if code[1:].isdigit() else sequence,
            }))
        values = {
            'formula_id': family.id,
            'version_number': self._next_version_number(family),
            'previous_version_id': previous_version.id if previous_version else False,
            'state': state,
            'origin': origin,
            'line_ids': line_commands,
            'source_mo_id': source_mo.id if source_mo else False,
            'source_bom_id': source_bom.id if source_bom else False,
            'import_batch_id': import_batch.id if import_batch else False,
            'notes': notes,
            'change_reason': change_reason,
        }
        version = self.create(values)
        family.with_context(allow_formula_system_write=True).write({'latest_version_id': version.id})
        _logger.info(
            "FORMULA_VERSION_CREATE_FROM_RECIPE family_id=%s version_id=%s state=%s "
            "origin=%s recipe=%s",
            family.id, version.id, state, origin, normalized,
        )
        return version

    def get_shots_dict(self):
        self.ensure_one()
        return dict(sorted({
            line.colorant_code: round(line.shots, 2)
            for line in self.line_ids if line.colorant_code and line.shots > 0
        }.items()))

    def _check_manager(self):
        if not self.env.user.has_group('paint_tinting.group_tint_formula_manager'):
            _logger.warning("FORMULA_MANAGER_ACCESS_DENIED user_id=%s version_ids=%s", self.env.user.id, self.ids)
            raise AccessError(_('Only Tinting Formula Managers can approve formula versions.'))

    def _validate_for_approval(self):
        service = self.env['tinting.formula.recipe.service']
        errors = []
        for version in self:
            if version.state not in ('draft', 'validated'):
                errors.append(_('%s is not Draft or Validated.', version.display_name))
                continue
            recipe = version.get_shots_dict()
            if not recipe:
                errors.append(_('%s has no colorants.', version.display_name))
            if version.version_number > 1 and not version.change_reason:
                errors.append(_('%s requires a change reason.', version.display_name))
            signature = service.signature(recipe)
            duplicate = version.formula_id.version_ids.filtered(
                lambda other: other != version and other.recipe_signature == signature
            )[:1]
            if duplicate:
                errors.append(_('%(version)s duplicates %(duplicate)s.',
                                version=version.display_name, duplicate=duplicate.display_name))
        if errors:
            _logger.warning("FORMULA_APPROVAL_VALIDATION_FAILED ids=%s errors=%s", self.ids, errors)
            raise ValidationError('\n'.join(errors))
        return True

    def action_approve(self, set_default=False):
        self._check_manager()
        self._validate_for_approval()
        now = fields.Datetime.now()
        for version in self:
            version.with_context(allow_formula_system_write=True).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_date': now,
            })
            family = version.formula_id
            should_default = set_default or not family.default_version_id
            if should_default:
                family._set_default_version(version)
            family.with_context(allow_formula_system_write=True).write({'state': 'approved'})
            version.message_post(body=_(
                'Formula version approved by %(user)s. Default version: %(default)s',
                user=self.env.user.display_name,
                default=_('Yes') if should_default else _('No'),
            ))
            _logger.info(
                "FORMULA_VERSION_APPROVED version_id=%s family_id=%s set_default=%s approver_id=%s",
                version.id, family.id, should_default, self.env.user.id,
            )
        return True

    def action_approve_set_default(self):
        return self.action_approve(set_default=True)

    def action_set_default(self):
        self._check_manager()
        for version in self:
            if version.state not in ('approved', 'superseded'):
                raise UserError(_('Only Approved or Superseded versions can be made default.'))
            version.formula_id._set_default_version(version)
        return True

    def increment_usage_counter(self):
        for version in self:
            version.with_context(allow_formula_system_write=True).write({
                'times_used': version.times_used + 1,
                'last_used_date': fields.Datetime.now(),
            })
            _logger.info(
                "FORMULA_VERSION_USAGE_INCREMENT version_id=%s count=%s user_id=%s",
                version.id, version.times_used, self.env.user.id,
            )


class TintingFormulaVersionLine(models.Model):
    _name = 'tinting.formula.version.line'
    _description = 'Tinting Formula Version Line'
    _order = 'sequence, colorant_code, id'

    version_id = fields.Many2one(
        'tinting.formula.version', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    colorant_id = fields.Many2one(
        'product.product', required=True,
        domain="[('product_tmpl_id.is_colorant', '=', True)]",
    )
    colorant_code = fields.Char(
        related='colorant_id.product_tmpl_id.colorant_code', store=True, readonly=True,
    )
    colorant_name = fields.Char(related='colorant_id.name', readonly=True)
    shots = fields.Float(required=True, digits=(10, 2))
    ml_volume = fields.Float(compute='_compute_volumes', store=True, digits=(10, 3))
    qty_litres = fields.Float(compute='_compute_volumes', store=True, digits=(10, 6))

    _sql_constraints = [
        ('version_colorant_unique', 'unique(version_id, colorant_id)',
         'A colorant may only appear once in a formula version.'),
        ('version_shots_positive', 'CHECK(shots > 0)', 'Shots must be greater than zero.'),
    ]

    @api.depends('shots')
    def _compute_volumes(self):
        for line in self:
            line.ml_volume = line.shots * 0.616
            line.qty_litres = line.ml_volume / 1000.0

    def write(self, vals):
        if not self.env.context.get('allow_formula_system_write'):
            locked = self.filtered(lambda line: line.version_id.state != 'draft')
            if locked:
                _logger.warning(
                    "FORMULA_VERSION_LINE_WRITE_BLOCKED ids=%s versions=%s user_id=%s",
                    locked.ids, locked.mapped('version_id').ids, self.env.user.id,
                )
                raise UserError(_('Colorant lines can only be edited on Draft versions.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('allow_formula_system_write') and self.filtered(
            lambda line: line.version_id.state != 'draft'
        ):
            raise UserError(_('Colorant lines can only be removed from Draft versions.'))
        return super().unlink()
