# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PaintTintingMistakeEmployeeLine(models.Model):
    _name = 'paint.tinting.mistake.employee.line'
    _description = 'Tinting Mistake Employee Responsibility'
    _order = 'responsibility_percent desc, id'

    mistake_id = fields.Many2one(
        'paint.tinting.mistake',
        string='Mistake',
        required=True,
        ondelete='cascade',
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Related User',
        related='employee_id.user_id',
        store=True,
        readonly=True,
    )
    role = fields.Selection([
        ('salesperson', 'Salesperson'),
        ('tinter', 'Tinter/Mixer'),
        ('cashier', 'Cashier'),
        ('supervisor', 'Supervisor'),
        ('stock_counter', 'Stock Counter'),
        ('reporter', 'Reporter'),
        ('other', 'Other'),
    ], string='Role', required=True, default='tinter')
    responsibility_percent = fields.Float(
        string='Responsibility %',
        default=100.0,
        digits=(5, 2),
    )
    recommended_penalty_amount = fields.Monetary(
        string='Recommended Penalty',
        currency_field='currency_id',
        compute='_compute_recommended_penalty_amount',
        store=True,
    )
    final_penalty_amount = fields.Monetary(
        string='Final Penalty',
        currency_field='currency_id',
    )
    forgiven = fields.Boolean(string='Forgiven')
    forgiveness_reason = fields.Text(string='Forgiveness Reason')
    notes = fields.Text(string='Notes')
    currency_id = fields.Many2one(
        related='mistake_id.currency_id',
        store=True,
        readonly=True,
    )

    @api.depends('mistake_id.recommended_recovery_amount', 'responsibility_percent')
    def _compute_recommended_penalty_amount(self):
        for line in self:
            line.recommended_penalty_amount = (
                line.mistake_id.recommended_recovery_amount
                * (line.responsibility_percent or 0.0)
                / 100.0
            )

    @api.onchange('forgiven')
    def _onchange_forgiven(self):
        for line in self:
            if line.forgiven:
                line.final_penalty_amount = 0.0

    @api.constrains('mistake_id', 'responsibility_percent')
    def _check_total_responsibility_percent(self):
        for line in self:
            total = sum(line.mistake_id.employee_line_ids.mapped('responsibility_percent'))
            if total > 100.0:
                raise ValidationError(_('Employee responsibility cannot exceed 100%.'))
