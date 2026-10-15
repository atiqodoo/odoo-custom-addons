# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestTeamKubwaResConfigSettings(TransactionCase):

    def test_require_transaction_ref_can_be_saved_true(self):
        settings = self.env['res.config.settings'].create({
            'team_kubwa_require_transaction_ref': True,
        })

        settings.set_values()
        loaded = self.env['res.config.settings'].default_get(['team_kubwa_require_transaction_ref'])

        self.assertTrue(loaded['team_kubwa_require_transaction_ref'])
        self.assertEqual(
            self.env['ir.config_parameter'].sudo().get_param('team_kubwa_cashout.require_transaction_ref'),
            'True',
        )

    def test_require_transaction_ref_defaults_false_when_missing(self):
        self.env['ir.config_parameter'].sudo().search([
            ('key', 'in', ['team_kubwa_cashout.require_transaction_ref', 'team_kubwa_cashout.require_crown_reference']),
        ]).unlink()

        loaded = self.env['res.config.settings'].default_get(['team_kubwa_require_transaction_ref'])

        self.assertFalse(loaded['team_kubwa_require_transaction_ref'])

    def test_require_transaction_ref_reads_legacy_crown_reference_setting(self):
        params = self.env['ir.config_parameter'].sudo()
        params.search([('key', '=', 'team_kubwa_cashout.require_transaction_ref')]).unlink()
        params.set_param('team_kubwa_cashout.require_crown_reference', 'True')

        loaded = self.env['res.config.settings'].default_get(['team_kubwa_require_transaction_ref'])

        self.assertTrue(loaded['team_kubwa_require_transaction_ref'])
