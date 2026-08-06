# -*- coding: utf-8 -*-
"""
stock_picking.py
================
Extends ``stock.picking`` with a single override of ``button_validate()``.

How the interception works
--------------------------
Odoo 18's ``button_validate()`` has a well-defined return contract:

  - Returns ``True``               → validation is done, no further dialog.
  - Returns a wizard action dict   → a pre-validation wizard (backorder or
                                     immediate-transfer) must be shown first;
                                     ``_action_done()`` has NOT run yet.
  - Returns a ``do_multi_print``   → validation is done + silent auto-prints
                                     from ``_get_autoprint_report_actions()``.

Our override calls ``super()`` first, then inspects the result:

  ┌─────────────────────────────┬────────────────────────────────────────┐
  │  super() result             │  Our action                            │
  ├─────────────────────────────┼────────────────────────────────────────┤
  │  True                       │  Return wizard act_window directly.    │
  │  do_multi_print dict        │  Set wizard as anotherAction so it     │
  │                             │  opens after all silent prints finish. │
  │  Any other action (dict)    │  Return as-is — this is a backorder /  │
  │                             │  immediate-transfer wizard; picking is  │
  │                             │  not done yet.  Our popup fires on the │
  │                             │  next button_validate() call after the │
  │                             │  operator resolves that wizard.        │
  └─────────────────────────────┴────────────────────────────────────────┘

We only intercept when ALL of the following are true:
  • picking_type_code == 'incoming'
  • picking_type_id.auto_label_popup_on_receipt is True
  • picking.state == 'done'   (confirms _action_done() ran successfully)
  • At least one move_line has quantity > 0

Logging
-------
Logger name: ``stock_receipt_label_auto_print.models.stock_picking``

  INFO   — wizard created / popup chained
  DEBUG  — per-picking filter decisions, return-action type inspection
  WARNING — popup skipped due to empty wizard lines or unexpected state
"""

import logging

from odoo import _, models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    """Injects the receipt label popup into the validate flow."""

    _inherit = 'stock.picking'

    # ------------------------------------------------------------------
    # Public override
    # ------------------------------------------------------------------

    def button_validate(self):
        """
        Override of stock.picking.button_validate().

        Calls super() first so all standard logic (backorder detection,
        _action_done, _get_autoprint_report_actions) runs unchanged.
        Then, if the result indicates that validation completed, chains the
        receipt label wizard into the return action for any done incoming
        receipts that have auto_label_popup_on_receipt enabled.
        """
        _logger.debug(
            '[button_validate] called on %d picking(s): %s',
            len(self),
            ', '.join(self.mapped('name')),
        )

        result = super().button_validate()

        _logger.debug(
            '[button_validate] super() returned: type=%s  tag=%s',
            type(result).__name__,
            result.get('tag') if isinstance(result, dict) else 'N/A',
        )

        # Filter to receipts that completed and have the popup enabled.
        # state == 'done' is the reliable signal that _action_done() ran.
        done_receipts = self._get_done_receipts_for_popup()

        if not done_receipts:
            _logger.debug(
                '[button_validate] no done receipts with popup enabled — '
                'returning result unchanged',
            )
            return result

        _logger.info(
            '[button_validate] building label popup wizard for: %s',
            ', '.join(done_receipts.mapped('name')),
        )

        wizard_action = self._build_receipt_label_wizard_action(done_receipts)

        if wizard_action is None:
            # Wizard was created but found zero lines (all qty_done == 0).
            # This is unexpected after a successful validation but handled
            # gracefully — we simply skip the popup.
            _logger.warning(
                '[button_validate] wizard returned no lines for %s — '
                'skipping popup, returning result unchanged',
                ', '.join(done_receipts.mapped('name')),
            )
            return result

        return self._chain_wizard_action(result, wizard_action)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_done_receipts_for_popup(self):
        """
        Returns the subset of ``self`` that:
          - Is an incoming receipt (picking_type_code == 'incoming')
          - Has state == 'done'  (i.e. _action_done() completed)
          - Has auto_label_popup_on_receipt enabled on its operation type
          - Has at least one move_line with a positive done quantity

        Logs a DEBUG line for every picking explaining why it was included
        or excluded, to simplify troubleshooting.
        """
        matching = self.env['stock.picking']

        for picking in self:
            code = picking.picking_type_id.code
            state = picking.state
            popup_on = picking.picking_type_id.auto_label_popup_on_receipt
            has_qty = any(
                ml.quantity > 0
                for ml in picking.move_line_ids
            )

            _logger.debug(
                '[filter] %s  code=%s  state=%s  popup_on=%s  has_qty=%s',
                picking.name, code, state, popup_on, has_qty,
            )

            if code == 'incoming' and state == 'done' and popup_on and has_qty:
                matching |= picking
            else:
                _logger.debug(
                    '[filter] %s excluded  (reason: code=%s, state=%s, '
                    'popup_on=%s, has_qty=%s)',
                    picking.name, code, state, popup_on, has_qty,
                )

        return matching

    def _build_receipt_label_wizard_action(self, pickings):
        """
        Creates a ``stock.receipt.label.wizard`` record pre-populated
        from the done move_lines of *pickings*, then builds and returns
        an ``ir.actions.act_window`` dict that opens it as a dialog.

        Returns ``None`` when the wizard ends up with no lines (all
        move_line quantities are effectively zero after rounding).

        Parameters
        ----------
        pickings : stock.picking recordset
            The validated receipt pickings to populate the wizard from.

        Returns
        -------
        dict or None
        """
        _logger.debug(
            '[build_wizard] creating wizard for %d picking(s): %s',
            len(pickings),
            ', '.join(pickings.mapped('name')),
        )

        wizard = self.env['stock.receipt.label.wizard'].create({
            'picking_ids': [(6, 0, pickings.ids)],
        })

        _logger.debug('[build_wizard] wizard record id=%d created', wizard.id)

        wizard._populate_lines()

        if not wizard.wizard_line_ids:
            _logger.warning(
                '[build_wizard] wizard id=%d has 0 lines after _populate_lines(). '
                'Pickings: %s',
                wizard.id,
                ', '.join(pickings.mapped('name')),
            )
            return None

        _logger.info(
            '[build_wizard] wizard id=%d ready with %d line(s)',
            wizard.id,
            len(wizard.wizard_line_ids),
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Print Receipt Labels'),
            'res_model': 'stock.receipt.label.wizard',
            'res_id': wizard.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'new',
        }

    def _chain_wizard_action(self, validate_result, wizard_action):
        """
        Merges *wizard_action* into *validate_result* using the correct
        chaining strategy depending on what ``button_validate()`` returned.

        Strategy:
          - result is True           → return wizard_action directly
          - result is do_multi_print → set wizard as ``anotherAction``
                                       so it opens after all silent prints
          - result is anything else  → return result unchanged (the picking
                                       is not yet done; we must not intercept)

        Parameters
        ----------
        validate_result : bool | dict
            The value returned by ``super().button_validate()``.
        wizard_action : dict
            The ``ir.actions.act_window`` action for the label popup wizard.

        Returns
        -------
        bool | dict
        """
        if validate_result is True:
            _logger.info(
                '[chain] validate_result=True → returning wizard_action directly',
            )
            return wizard_action

        if isinstance(validate_result, dict):
            tag = validate_result.get('tag')

            if tag == 'do_multi_print':
                self._remove_builtin_label_reports(validate_result)
                existing_another = validate_result['params'].get('anotherAction')

                if existing_another:
                    # anotherAction already occupied (e.g. reception report).
                    # Our label popup takes priority for warehouse operations;
                    # the reception report is still accessible via the
                    # 'Forecasted Demand' smart button on the picking.
                    _logger.info(
                        '[chain] do_multi_print already has anotherAction '
                        '(type=%s) — replacing with label wizard',
                        existing_another.get('type', 'unknown'),
                    )
                else:
                    _logger.info(
                        '[chain] do_multi_print has no anotherAction — '
                        'setting label wizard as anotherAction',
                    )

                validate_result['params']['anotherAction'] = wizard_action
                return validate_result

            # Some other action dict — backorder wizard, immediate-transfer
            # wizard, or reception report returned directly (no silent prints).
            # We must not intercept: the picking state may not be 'done' yet
            # from the user's perspective.  The popup will fire on the next
            # button_validate() call after the operator resolves the dialog.
            _logger.debug(
                '[chain] validate_result is dict with tag=%s — '
                'not a recognised chainable action; returning unchanged',
                tag,
            )
            return validate_result

        # Unexpected return type — pass through safely.
        _logger.warning(
            '[chain] unexpected validate_result type=%s value=%s — '
            'returning unchanged',
            type(validate_result).__name__,
            validate_result,
        )
        return validate_result

    def _remove_builtin_label_reports(self, validate_result):
        """Drop Odoo's silent label reports when our review popup is active."""
        params = validate_result.get('params') or {}
        reports = params.get('reports') or []
        label_report_names = {
            'stock.label_product_product_view',
            'stock.label_lot_template_view',
        }

        kept_reports = []
        removed_reports = []
        for report in reports:
            report_name = report.get('report_name')
            if report_name in label_report_names:
                removed_reports.append(report.get('name') or report_name)
            else:
                kept_reports.append(report)

        if removed_reports:
            _logger.info(
                '[chain] removed built-in label auto-print report(s): %s',
                ', '.join(removed_reports),
            )
            params['reports'] = kept_reports
