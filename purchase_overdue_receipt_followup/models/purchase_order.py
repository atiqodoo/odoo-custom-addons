import logging

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _rfq_scheduler_jobs(self):
        """Specific existing jobs only; keep scheduling and procurement in Odoo."""
        return (self.env.ref('stock.ir_cron_scheduler_action')
                | self.env.ref('purchase_overdue_receipt_followup.cron_overdue_receipt_followup'))

    def action_run_scheduler_from_rfq(self):
        # This entry point is database-wide like the Inventory scheduler, rather
        # than a purchase operation on the selected RFQ rows. Do not elevate buyers.
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only system administrators can run the database-wide procurement scheduler.'))
        jobs = self._rfq_scheduler_jobs()
        jobs.check_access('write')
        _logger.debug('[OVERDUE_RECEIPT][RFQ_SCHEDULER][START] user_id=%s job_ids=%s', self.env.uid, jobs.ids)
        try:
            if any(not job.active for job in jobs):
                raise UserError(_('Enable the Procurement and Overdue Receipt scheduled actions before requesting a run.'))
            now = fields.Datetime.now()
            pending = self.env['ir.cron.trigger'].search([
                ('cron_id', 'in', jobs.ids), ('call_at', '<=', now),
            ]).cron_id
            queued = 0
            for job in jobs - pending:
                # The native trigger wakes the cron worker, respects its job locks,
                # and leaves nextcall, execution user and regular frequency intact.
                queued += len(job._trigger())
            _logger.debug('[OVERDUE_RECEIPT][RFQ_SCHEDULER][END] user_id=%s queued=%s already_pending=%s',
                          self.env.uid, queued, len(pending))
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {
                    'title': _('Scheduler Requested'),
                    'message': _('Procurement and overdue receipt checks are queued to run in the background. Receiving calendar rules still apply.'),
                    'type': 'info', 'sticky': False,
                },
            }
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][RFQ_SCHEDULER][ERROR] user_id=%s job_ids=%s',
                              self.env.uid, jobs.ids)
            raise
