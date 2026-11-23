"""Native read-only reports. SQL is used for aggregation and historical windows.

Both reports share one movement query, so audit events and legacy history are
never counted twice. Company scope is applied inside queries as well as by rules.
"""
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL

_logger = logging.getLogger(__name__)
_DIGITS = (16, 6)
_REPORT_CONTEXT = ("lpm_date_from", "lpm_date_to", "lpm_as_of", "lpm_dormant_days",
                   "allowed_company_ids", "uid", "tz")
_SOURCE_TYPES = [("pos", "POS"), ("sale", "Sales"), ("manual", "Manual"),
                 ("import", "Import / Balance Sync"), ("other", "Other")]
_DEPENDS = {
    "loyalty.card": ["points", "partner_id", "program_id", "company_id", "create_date"],
    "loyalty.program": ["program_type"],
    "loyalty.history": ["issued", "used", "card_id", "order_model", "order_id", "create_date"],
    "loyalty.audit.event": ["issued", "used", "card_id", "history_id", "company_id", "captured_at",
                            "balance_before", "policy", "origin_session_id", "collection_session_id",
                            "source_model", "source_order_id", "source_reference", "evidence_quality"],
    "pos.order": ["session_id", "partner_id", "company_id", "state", "date_order", "amount_total", "cod_state"],
    "sale.order": ["partner_id", "company_id", "state", "date_order", "amount_total"],
}


class LoyaltyReportService(models.AbstractModel):
    _name = "loyalty.report.service"
    _description = "Loyalty Reporting Queries"

    @api.model
    def _parameters(self):
        today = fields.Date.context_today(self)
        context = self.env.context
        date_from = fields.Date.to_date(context.get("lpm_date_from"))
        date_to = fields.Date.to_date(context.get("lpm_date_to")) or today
        as_of = fields.Date.to_date(context.get("lpm_as_of")) or today
        dormant_days = int(context.get("lpm_dormant_days", 0))
        if date_from and date_from > date_to:
            raise ValidationError(_("The period start must not be after its end."))
        if as_of > today or dormant_days < 0:
            raise ValidationError(_("Choose a balance date up to today and a non-negative inactivity period."))
        zone = pytz.timezone(context.get("tz") or self.env.user.tz or "UTC")

        def boundary(day):
            return zone.localize(datetime.combine(day, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)

        return {
            "from": boundary(date_from) if date_from else None,
            "until": boundary(date_to + timedelta(days=1)),
            "as_of_until": boundary(as_of + timedelta(days=1)),
            "as_of": as_of, "today": today, "dormant_days": dormant_days,
            "timezone": zone.zone, "companies": tuple(self.env.companies.ids),
        }

    @api.model
    def _movement_query(self):
        """One row per captured event or uncovered portion of legacy history."""
        companies = self._parameters()["companies"]
        return SQL("""
            WITH event_totals AS (
                SELECT history_id, SUM(issued) issued, SUM(used) used
                FROM loyalty_audit_event WHERE history_id IS NOT NULL GROUP BY history_id
            ), movements AS (
                SELECT e.id * 2 AS id, e.captured_at AS date, e.company_id,
                       c.partner_id, c.program_id, c.id card_id, e.history_id, e.id event_id,
                       e.source_model, e.source_order_id, e.source_reference,
                       CASE WHEN e.policy = 'actual_cancellation_movement' THEN 0 ELSE e.issued END AS issued,
                       e.used,
                       CASE WHEN e.policy = 'actual_cancellation_movement' THEN e.issued ELSE 0 END AS adjustment_points,
                       e.issued - e.used AS net_points,
                       'captured'::varchar AS date_quality,
                       COALESCE(e.origin_session_id, po.session_id) AS origin_session_id,
                       e.collection_session_id,
                       e.evidence_quality
                FROM loyalty_audit_event e JOIN loyalty_card c ON c.id = e.card_id
                LEFT JOIN pos_order po ON e.source_model = 'pos.order' AND po.id = e.source_order_id
                WHERE e.company_id IN %s AND (c.company_id IS NULL OR c.company_id IN %s)
                UNION ALL
                SELECT h.id * 2 + 1, h.create_date, COALESCE(po.company_id, so.company_id, c.company_id),
                       c.partner_id, c.program_id, c.id, h.id, NULL::integer,
                       h.order_model, h.order_id, COALESCE(po.name, so.name, h.description),
                       h.issued - COALESCE(t.issued, 0), h.used - COALESCE(t.used, 0), 0,
                       h.issued - COALESCE(t.issued, 0) - h.used + COALESCE(t.used, 0),
                       'reconstructed'::varchar, po.session_id, NULL::integer, 'partial'::varchar
                FROM loyalty_history h JOIN loyalty_card c ON c.id = h.card_id
                LEFT JOIN event_totals t ON t.history_id = h.id
                LEFT JOIN pos_order po ON h.order_model = 'pos.order' AND po.id = h.order_id
                LEFT JOIN sale_order so ON h.order_model = 'sale.order' AND so.id = h.order_id
                WHERE (c.company_id IS NULL OR c.company_id IN %s)
                  AND (COALESCE(po.company_id, so.company_id, c.company_id) IS NULL
                       OR COALESCE(po.company_id, so.company_id, c.company_id) IN %s)
                  AND (t.history_id IS NULL OR ROUND((h.issued - t.issued)::numeric, 6) != 0
                       OR ROUND((h.used - t.used)::numeric, 6) != 0)
            )
            SELECT m.*,
                   CASE m.source_model WHEN 'pos.order' THEN 'pos' WHEN 'sale.order' THEN 'sale'
                        WHEN 'loyalty.points.adjustment' THEN 'manual' WHEN 'res.partner' THEN 'import'
                        ELSE 'other' END AS source_type,
                   CASE WHEN m.source_model = 'pos.order' THEN m.source_order_id END AS pos_order_id,
                   CASE WHEN m.source_model = 'sale.order' THEN m.source_order_id END AS sale_order_id
            FROM movements m JOIN loyalty_program p ON p.id = m.program_id
            WHERE p.program_type = 'loyalty' AND m.partner_id IS NOT NULL
        """, companies, companies, companies, companies)

    @api.model
    def _summary_query(self):
        p = self._parameters()
        _logger.debug("[LPM][REPORT][START] operation=summary_query companies=%s as_of=%s dormant_days=%s",
                      p["companies"], p["as_of"], p["dormant_days"])
        query = SQL("""
            WITH movements AS (%s), options AS (
                SELECT %s::timestamp AS period_from, %s::timestamp AS period_until,
                       %s::timestamp AS as_of_until, %s::date AS as_of_date,
                       %s::date AS today, %s::integer AS dormant_days, %s::varchar AS timezone
            ), cards AS (
                SELECT c.id, c.partner_id, c.program_id, c.company_id, c.points, c.create_date,
                       MIN(c.id) OVER (PARTITION BY c.partner_id, c.program_id, c.company_id) AS group_id
                FROM loyalty_card c JOIN loyalty_program p ON p.id = c.program_id
                WHERE c.partner_id IS NOT NULL AND p.program_type = 'loyalty'
                  AND (c.company_id IS NULL OR c.company_id IN %s)
            ), anchors AS (
                SELECT DISTINCT ON (e.card_id) e.card_id, e.captured_at AS date, e.balance_before
                FROM loyalty_audit_event e JOIN cards c ON c.id = e.card_id
                WHERE e.company_id IN %s ORDER BY e.card_id, e.captured_at, e.id
            ), card_stats AS (
                SELECT c.*, COALESCE(a.date, c.create_date) AS coverage_start,
                       COALESCE(a.balance_before, 0) AS opening,
                       a.card_id IS NOT NULL AS has_anchor,
                       ROUND((c.points - COALESCE(a.balance_before, 0) - COALESCE(SUM(m.net_points)
                           FILTER (WHERE m.date >= COALESCE(a.date, c.create_date)), 0))::numeric, 6) = 0 AS reconciled,
                       COUNT(m.id) FILTER (WHERE m.date_quality = 'reconstructed') AS legacy_count,
                       COALESCE(SUM(m.issued), 0) AS lifetime_issued,
                       COALESCE(SUM(m.used), 0) AS lifetime_used,
                       COALESCE(SUM(m.adjustment_points), 0) AS lifetime_adjustments,
                       COALESCE(SUM(m.issued) FILTER (WHERE (o.period_from IS NULL OR m.date >= o.period_from)
                           AND m.date < o.period_until), 0) AS period_issued,
                       COALESCE(SUM(m.used) FILTER (WHERE (o.period_from IS NULL OR m.date >= o.period_from)
                           AND m.date < o.period_until), 0) AS period_used,
                       MAX(m.date) FILTER (WHERE m.issued > 0 AND m.date < o.as_of_until) AS last_earning,
                       MAX(m.date) FILTER (WHERE m.used > 0 AND m.date < o.as_of_until) AS last_redemption,
                       COALESCE(SUM(m.net_points) FILTER (WHERE m.date >= COALESCE(a.date, c.create_date)
                           AND m.date < o.as_of_until), 0) AS net_to_date
                FROM cards c LEFT JOIN anchors a ON a.card_id = c.id
                CROSS JOIN options o LEFT JOIN movements m ON m.card_id = c.id
                GROUP BY c.id, c.program_id, c.company_id, c.partner_id, c.points, c.create_date, c.group_id,
                         a.date, a.card_id, a.balance_before
            ), groups AS (
                SELECT group_id AS id, partner_id, program_id, company_id,
                       COUNT(*) AS card_count, SUM(points) AS current_balance,
                       SUM(lifetime_issued) AS lifetime_issued, SUM(lifetime_used) AS lifetime_used,
                       SUM(lifetime_adjustments) AS lifetime_adjustments,
                       SUM(period_issued) AS period_issued, SUM(period_used) AS period_used,
                       MAX(last_earning) AS last_earning, MAX(last_redemption) AS last_redemption,
                       MAX(coverage_start) FILTER (WHERE create_date < o.as_of_until) AS coverage_start,
                       COALESCE(BOOL_AND(reconciled) FILTER (WHERE create_date < o.as_of_until), TRUE) AS reconciled,
                       COALESCE(BOOL_AND(has_anchor AND legacy_count = 0)
                           FILTER (WHERE create_date < o.as_of_until), FALSE) AS captured,
                       BOOL_AND(create_date >= o.as_of_until OR coverage_start < o.as_of_until) AS covered_as_of,
                       SUM(CASE WHEN create_date >= o.as_of_until THEN 0 ELSE opening + net_to_date END) AS reconstructed_balance
                FROM card_stats CROSS JOIN options o
                GROUP BY group_id, partner_id, program_id, company_id
            ), baseline_card_net AS (
                SELECT c.id, COALESCE(SUM(m.net_points) FILTER (
                    WHERE m.date >= c.coverage_start AND m.date < g.coverage_start
                ), 0) AS net FROM card_stats c JOIN groups g ON g.id = c.group_id
                LEFT JOIN movements m ON m.card_id = c.id GROUP BY c.id
            ), baselines AS (
                SELECT g.id, COALESCE(SUM(c.opening + bn.net)
                    FILTER (WHERE c.create_date < o.as_of_until), 0) AS balance
                FROM groups g JOIN card_stats c ON c.group_id = g.id
                JOIN baseline_card_net bn ON bn.id = c.id CROSS JOIN options o GROUP BY g.id
            ), timeline AS (
                SELECT c.group_id, m.id, m.date, m.net_points AS delta
                FROM movements m JOIN cards c ON c.id = m.card_id JOIN groups g ON g.id = c.group_id
                CROSS JOIN options o WHERE m.date >= g.coverage_start AND m.date < o.as_of_until
            ), running AS (
                SELECT t.group_id, t.id, t.date, b.balance + SUM(t.delta) OVER (
                    PARTITION BY t.group_id ORDER BY t.date, t.id ROWS UNBOUNDED PRECEDING
                ) AS balance FROM timeline t JOIN baselines b ON b.id = t.group_id
            ), peaks AS (
                SELECT DISTINCT ON (group_id) group_id, date, balance
                FROM running ORDER BY group_id, balance DESC, date, id
            ), purchases AS (
                SELECT partner_id, company_id, date_order AS date FROM pos_order
                WHERE state IN ('paid', 'done', 'invoiced') AND amount_total > 0
                  AND company_id IN %s AND (cod_state IS NULL OR cod_state != 'returned')
                UNION ALL
                SELECT partner_id, company_id, date_order FROM sale_order
                WHERE state = 'sale' AND amount_total > 0 AND company_id IN %s
            ), last_purchases AS (
                SELECT g.id, MAX(p.date) AS date FROM groups g CROSS JOIN options o
                LEFT JOIN purchases p ON p.partner_id = g.partner_id AND p.date < o.as_of_until
                    AND (g.company_id IS NULL OR p.company_id = g.company_id) GROUP BY g.id
            )
            SELECT g.id, g.partner_id, g.program_id, g.company_id, g.card_count,
                   g.current_balance, g.lifetime_issued, g.lifetime_used, g.lifetime_adjustments,
                   g.period_issued, g.period_used, g.last_earning, g.last_redemption,
                   o.as_of_date, o.dormant_days, g.coverage_start AS historical_coverage_start,
                   CASE WHEN o.as_of_date = o.today THEN g.current_balance
                        WHEN g.reconciled AND g.covered_as_of THEN g.reconstructed_balance END AS balance_as_of,
                   CASE WHEN o.as_of_date = o.today THEN 'current'
                        WHEN NOT g.reconciled OR NOT g.covered_as_of THEN 'unavailable'
                        WHEN g.captured THEN 'captured' ELSE 'reconstructed' END AS balance_quality,
                   CASE WHEN g.reconciled AND g.covered_as_of
                        THEN GREATEST(b.balance, COALESCE(pk.balance, b.balance)) END AS peak_recorded_balance,
                   CASE WHEN g.reconciled AND g.covered_as_of THEN
                        CASE WHEN b.balance >= COALESCE(pk.balance, b.balance) THEN g.coverage_start ELSE pk.date END END AS peak_date,
                   CASE WHEN NOT g.reconciled OR NOT g.covered_as_of THEN 'unavailable'
                        WHEN g.captured THEN 'captured' ELSE 'reconstructed' END AS peak_quality,
                   lp.date AS last_purchase,
                   o.as_of_date - (lp.date AT TIME ZONE 'UTC' AT TIME ZONE o.timezone)::date AS days_since_purchase,
                   (o.dormant_days > 0 AND lp.date IS NOT NULL AND
                    o.as_of_date - (lp.date AT TIME ZONE 'UTC' AT TIME ZONE o.timezone)::date >= o.dormant_days) AS dormant,
                   lp.date IS NULL AS never_purchased,
                   g.lifetime_used = 0 AS never_redeemed
            FROM groups g CROSS JOIN options o JOIN baselines b ON b.id = g.id
            LEFT JOIN peaks pk ON pk.group_id = g.id JOIN last_purchases lp ON lp.id = g.id
        """, self._movement_query(), p["from"], p["until"], p["as_of_until"], p["as_of"],
            p["today"], p["dormant_days"], p["timezone"], p["companies"], p["companies"],
            p["companies"], p["companies"])
        _logger.debug("[LPM][REPORT][END] operation=summary_query outcome=query_built")
        return query


class LoyaltyMovementReport(models.Model):
    _name = "loyalty.movement.report"
    _description = "Loyalty Point Movements"
    _auto = False
    _rec_name = "source_reference"
    _order = "date desc, id desc"
    _depends = _DEPENDS

    date = fields.Datetime(readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    program_id = fields.Many2one("loyalty.program", readonly=True)
    card_id = fields.Many2one("loyalty.card", readonly=True)
    history_id = fields.Many2one("loyalty.history", readonly=True)
    event_id = fields.Many2one("loyalty.audit.event", readonly=True)
    source_model = fields.Char(readonly=True)
    source_order_id = fields.Integer(readonly=True)
    source_reference = fields.Char(readonly=True)
    source_type = fields.Selection(_SOURCE_TYPES, readonly=True)
    pos_order_id = fields.Many2one("pos.order", string="POS Order", readonly=True)
    sale_order_id = fields.Many2one("sale.order", string="Sales Order", readonly=True)
    origin_session_id = fields.Many2one("pos.session", string="Order POS Session", readonly=True)
    collection_session_id = fields.Many2one("pos.session", string="COD Collection Session", readonly=True)
    issued = fields.Float(string="Issued Points", digits=_DIGITS, readonly=True)
    used = fields.Float(string="Used Points", digits=_DIGITS, readonly=True)
    adjustment_points = fields.Float(string="Cancellation Adjustments", digits=_DIGITS, readonly=True)
    net_points = fields.Float(digits=_DIGITS, readonly=True)
    date_quality = fields.Selection([("captured", "Captured movement time"),
                                    ("reconstructed", "Legacy history creation time")], readonly=True)
    evidence_quality = fields.Selection([("captured", "Captured"), ("partial", "Partial")], readonly=True)

    @property
    def _table_query(self):
        service = self.env["loyalty.report.service"]
        p = service._parameters()
        _logger.debug("[LPM][REPORT][START] operation=movement_query companies=%s", p["companies"])
        query = SQL("SELECT * FROM (%s) m WHERE (%s::timestamp IS NULL OR date >= %s::timestamp) AND date < %s::timestamp",
                    service._movement_query(), p["from"], p["from"], p["until"])
        _logger.debug("[LPM][REPORT][END] operation=movement_query outcome=query_built")
        return query


class LoyaltyCustomerReport(models.Model):
    _name = "loyalty.customer.report"
    _description = "Customer Loyalty Summary"
    _auto = False
    _rec_name = "partner_id"
    _order = "current_balance desc, id"
    _depends = _DEPENDS

    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    program_id = fields.Many2one("loyalty.program", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    card_count = fields.Integer(readonly=True)
    current_balance = fields.Float(digits=_DIGITS, readonly=True)
    balance_as_of = fields.Float(digits=_DIGITS, readonly=True, depends_context=_REPORT_CONTEXT)
    as_of_date = fields.Date(readonly=True, depends_context=_REPORT_CONTEXT)
    balance_quality = fields.Selection([("current", "Current live balance"), ("captured", "Captured interval"),
        ("reconstructed", "Reconstructed ledger"), ("unavailable", "Insufficient history")], readonly=True, depends_context=_REPORT_CONTEXT)
    peak_recorded_balance = fields.Float(digits=_DIGITS, readonly=True, aggregator=False, depends_context=_REPORT_CONTEXT,
        help="Peak of the combined customer balance over the available coverage interval; not a sum of individual card peaks.")
    peak_date = fields.Datetime(readonly=True, depends_context=_REPORT_CONTEXT)
    peak_quality = fields.Selection([("captured", "Captured interval"), ("reconstructed", "Reconstructed ledger"),
                                    ("unavailable", "Insufficient history")], readonly=True, depends_context=_REPORT_CONTEXT)
    historical_coverage_start = fields.Datetime(readonly=True, depends_context=_REPORT_CONTEXT)
    lifetime_issued = fields.Float(string="Recorded Issued (All Time)", digits=_DIGITS, readonly=True, depends_context=_REPORT_CONTEXT)
    lifetime_used = fields.Float(string="Recorded Used (All Time)", digits=_DIGITS, readonly=True, depends_context=_REPORT_CONTEXT)
    lifetime_adjustments = fields.Float(string="Cancellation Adjustments", digits=_DIGITS, readonly=True, depends_context=_REPORT_CONTEXT)
    period_issued = fields.Float(digits=_DIGITS, readonly=True, depends_context=_REPORT_CONTEXT)
    period_used = fields.Float(digits=_DIGITS, readonly=True, depends_context=_REPORT_CONTEXT)
    last_purchase = fields.Datetime(readonly=True, depends_context=_REPORT_CONTEXT)
    last_earning = fields.Datetime(readonly=True, depends_context=_REPORT_CONTEXT)
    last_redemption = fields.Datetime(readonly=True, depends_context=_REPORT_CONTEXT)
    days_since_purchase = fields.Integer(readonly=True, aggregator=False, depends_context=_REPORT_CONTEXT)
    dormant_days = fields.Integer(string="Dormancy Threshold (Days)", readonly=True, aggregator=False, depends_context=_REPORT_CONTEXT)
    dormant = fields.Boolean(readonly=True, depends_context=_REPORT_CONTEXT)
    never_purchased = fields.Boolean(readonly=True, depends_context=_REPORT_CONTEXT)
    never_redeemed = fields.Boolean(readonly=True, depends_context=_REPORT_CONTEXT)

    @property
    def _table_query(self):
        return self.env["loyalty.report.service"]._summary_query()

    def action_open_movements(self):
        self.ensure_one()
        self.check_access("read")
        action = self.env["ir.actions.actions"]._for_xml_id("loyalty_points_manager.action_loyalty_movement_report")
        action["domain"] = [("partner_id", "=", self.partner_id.id), ("program_id", "=", self.program_id.id)]
        if self.company_id:
            action["domain"].append(("company_id", "=", self.company_id.id))
        action["context"] = dict(self.env.context)
        return action
