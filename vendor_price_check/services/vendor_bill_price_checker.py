# -*- coding: utf-8 -*-
import logging

from odoo import _, fields
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)

PRICE_CHECK_LOG_HEAD = '[VPC_FINAL_UNIT_CHECK]'
PRICE_CONFIG_LOG_HEAD = '[VPC_FINAL_UNIT_CONFIG]'
PRICE_HISTORY_LOG_HEAD = '[VPC_FINAL_UNIT_HISTORY]'
PRICE_NO_HISTORY_LOG_HEAD = '[VPC_FINAL_UNIT_NO_HISTORY]'
PRICE_RECORD_LOG_HEAD = '[VPC_FINAL_UNIT_RECORD]'


class VendorBillPriceCheckConfig:
    """Read price-check settings from one place."""

    BILL_COUNT_PARAM = 'vendor_price_check.price_check_bill_count'
    COMPARISON_MODE_PARAM = 'vendor_price_check.comparison_mode'
    NO_HISTORY_POLICY_PARAM = 'vendor_price_check.no_history_policy'

    def __init__(self, env):
        self.env = env
        self.params = env['ir.config_parameter'].sudo()

    def get_bill_count(self):
        raw_value = self.params.get_param(self.BILL_COUNT_PARAM, '3')
        try:
            count = max(int(raw_value or 0), 0)
        except ValueError:
            count = 0
        _logger.info(
            '%s bill_count=%s raw=%s param=%s',
            PRICE_CONFIG_LOG_HEAD,
            count,
            raw_value,
            self.BILL_COUNT_PARAM,
        )
        return count

    def get_comparison_mode(self):
        mode = self.params.get_param(self.COMPARISON_MODE_PARAM, 'both') or 'both'
        if mode not in ('lowest', 'average', 'both'):
            mode = 'both'
        return mode

    def get_no_history_policy(self):
        policy = self.params.get_param(self.NO_HISTORY_POLICY_PARAM, 'skip') or 'skip'
        if policy not in ('skip', 'warn', 'block'):
            policy = 'skip'
        return policy


class UnitPriceInclVatCalculator:
    """Calculate final unit price including VAT from persisted bill lines."""

    def __init__(self, env):
        self.env = env

    def calculate(self, line, target_currency=False):
        currency = line.currency_id or line.move_id.currency_id or line.company_currency_id
        partner = line.partner_id or line.move_id.partner_id
        unit_price = line.price_unit or 0.0
        if line.tax_ids:
            tax_result = line.tax_ids.compute_all(
                unit_price,
                currency=currency,
                quantity=1.0,
                product=line.product_id,
                partner=partner,
            )
            price = tax_result['total_included']
        else:
            price = unit_price

        if target_currency and currency and currency != target_currency:
            price = currency._convert(
                price,
                target_currency,
                line.company_id,
                line.move_id.invoice_date or line.move_id.date or fields.Date.context_today(line),
            )
        return price


class HistoricalBillEligibilityPolicy:
    """Extension point for deciding whether a posted bill can be used as history."""

    def is_eligible_move(self, move):
        return move._is_eligible_for_vendor_price_history()


class HistoricalBillLineRepository:
    """Find latest eligible posted bill lines for a variant/vendor/company scope."""

    def __init__(self, env, calculator, eligibility_policy=None):
        self.env = env
        self.calculator = calculator
        self.eligibility_policy = eligibility_policy or HistoricalBillEligibilityPolicy()

    def find_prices(self, current_line, bill_count):
        move = current_line.move_id
        commercial_vendor = move.partner_id.commercial_partner_id
        target_currency = current_line.currency_id or move.currency_id
        if not bill_count:
            _logger.info(
                '%s disabled bill_id=%s line_id=%s product_id=%s reason=zero_count',
                PRICE_HISTORY_LOG_HEAD,
                move.id,
                current_line.id,
                current_line.product_id.id,
            )
            return []

        domain = [
            ('product_id', '=', current_line.product_id.id),
            ('move_id.move_type', '=', 'in_invoice'),
            ('move_id.state', '=', 'posted'),
            ('move_id.id', '!=', move.id),
            ('move_id.company_id', '=', move.company_id.id),
            ('move_id.partner_id.commercial_partner_id', '=', commercial_vendor.id),
            ('quantity', '!=', 0),
        ]
        if 'display_type' in current_line._fields:
            domain.append(('display_type', 'not in', ('line_section', 'line_note')))

        historical_lines = self.env['account.move.line'].search(
            domain,
            order='date desc, move_id desc, id desc',
        )

        selected_bill_ids = []
        prices = []
        for historical_line in historical_lines:
            historical_move = historical_line.move_id
            if not self.eligibility_policy.is_eligible_move(historical_move):
                _logger.info(
                    '%s skipped bill_id=%s line_id=%s product_id=%s payment_state=%s promotion_hold=%s',
                    PRICE_HISTORY_LOG_HEAD,
                    historical_move.id,
                    historical_line.id,
                    historical_line.product_id.id,
                    getattr(historical_move, 'payment_state', False),
                    getattr(historical_move, 'promotion_payment_hold', False),
                )
                continue
            if historical_move.id not in selected_bill_ids:
                if len(selected_bill_ids) >= bill_count:
                    break
                selected_bill_ids.append(historical_move.id)

            price = self.calculator.calculate(historical_line, target_currency=target_currency)
            if price <= 0:
                continue
            prices.append({
                'line': historical_line,
                'bill': historical_move,
                'price': price,
            })

        _logger.info(
            '%s selected bill_id=%s line_id=%s product_id=%s vendor_id=%s count_setting=%s '
            'selected_bill_ids=%s price_count=%s prices=%s',
            PRICE_HISTORY_LOG_HEAD,
            move.id,
            current_line.id,
            current_line.product_id.id,
            commercial_vendor.id,
            bill_count,
            selected_bill_ids,
            len(prices),
            [item['price'] for item in prices],
        )
        return prices


class NoHistoryPolicy:
    """Handle variants that have no same-vendor posted bill history."""

    def __init__(self, policy='skip'):
        self.policy = policy

    def apply(self, bill, line):
        _logger.warning(
            '%s bill_id=%s line_id=%s product_id=%s vendor_id=%s policy=%s',
            PRICE_NO_HISTORY_LOG_HEAD,
            bill.id,
            line.id,
            line.product_id.id,
            bill.partner_id.commercial_partner_id.id,
            self.policy,
        )
        if self.policy == 'block':
            raise ValidationError(_(
                'No eligible posted bill history exists for %(product)s from %(vendor)s.',
                product=line.product_id.display_name,
                vendor=bill.partner_id.commercial_partner_id.display_name,
            ))
        return []


class HistoricalComparisonPolicy:
    """Compare the current final VAT-inclusive price with history."""

    def __init__(self, comparison_mode='both'):
        self.comparison_mode = comparison_mode

    def compare(self, current_price, history):
        prices = [item['price'] for item in history]
        lowest_price = min(prices)
        average_price = sum(prices) / len(prices)
        price_diff_lowest = current_price - lowest_price
        price_diff_average = current_price - average_price
        percentage_diff_lowest = (
            (price_diff_lowest / lowest_price * 100.0) if lowest_price else 100.0
        )
        percentage_diff_average = (
            (price_diff_average / average_price * 100.0) if average_price else 100.0
        )
        is_discrepancy = (
            self.comparison_mode in ('lowest', 'both') and price_diff_lowest > 0.01
        ) or (
            self.comparison_mode in ('average', 'both') and price_diff_average > 0.01
        )
        lowest_item = min(history, key=lambda item: item['price'])
        historical_bill_ids = []
        history_line_values = []
        for item in history:
            bill_id = item['bill'].id
            if bill_id not in historical_bill_ids:
                historical_bill_ids.append(bill_id)
            history_line_values.append((0, 0, {
                'bill_id': item['bill'].id,
                'bill_line_id': item['line'].id,
                'final_unit_price_vat_incl': item['price'],
                'invoice_date': item['bill'].invoice_date or item['bill'].date,
            }))
        return {
            'is_discrepancy': is_discrepancy,
            'lowest_price': lowest_price,
            'average_price': average_price,
            'price_difference_lowest': price_diff_lowest,
            'percentage_diff_lowest': percentage_diff_lowest,
            'price_difference_average': price_diff_average,
            'percentage_diff_average': percentage_diff_average,
            'bill_count': len(historical_bill_ids),
            'lowest_bill_id': lowest_item['bill'].id,
            'historical_bill_ids': historical_bill_ids,
            'history_line_values': history_line_values,
        }


class DiscrepancyRecorder:
    """Persist final-unit price discrepancy records."""

    def __init__(self, env):
        self.env = env

    def create(self, bill, line, current_price, comparison):
        discrepancy = self.env['vendor.price.discrepancy'].create({
            'bill_id': bill.id,
            'product_id': line.product_id.id,
            'vendor_id': bill.partner_id.id,
            'vendor_price': current_price,
            'lowest_price': comparison['lowest_price'],
            'average_price': comparison['average_price'],
            'price_difference_lowest': comparison['price_difference_lowest'],
            'percentage_diff_lowest': comparison['percentage_diff_lowest'],
            'price_difference_average': comparison['price_difference_average'],
            'percentage_diff_average': comparison['percentage_diff_average'],
            'bill_count': comparison['bill_count'],
            'lowest_bill_id': comparison['lowest_bill_id'],
            'historical_bill_ids': [(6, 0, comparison['historical_bill_ids'])],
            'history_line_ids': comparison['history_line_values'],
        })
        _logger.warning(
            '%s created discrepancy_id=%s bill_id=%s line_id=%s product_id=%s '
            'current_final_unit_incl=%s lowest=%s average=%s bill_count=%s '
            'lowest_bill_id=%s historical_bill_ids=%s',
            PRICE_RECORD_LOG_HEAD,
            discrepancy.id,
            bill.id,
            line.id,
            line.product_id.id,
            current_price,
            comparison['lowest_price'],
            comparison['average_price'],
            comparison['bill_count'],
            comparison['lowest_bill_id'],
            comparison['historical_bill_ids'],
        )
        return discrepancy


class VendorBillFinalUnitPriceChecker:
    """Coordinate final VAT-inclusive unit price checks for vendor bills."""

    def __init__(
        self,
        env,
        config=None,
        calculator=None,
        repository=None,
        comparison_policy=None,
        no_history_policy=None,
        recorder=None,
    ):
        self.env = env
        self.config = config or VendorBillPriceCheckConfig(env)
        self.calculator = calculator or UnitPriceInclVatCalculator(env)
        self.repository = repository or HistoricalBillLineRepository(env, self.calculator)
        self.comparison_policy = comparison_policy
        self.no_history_policy = no_history_policy
        self.recorder = recorder or DiscrepancyRecorder(env)

    def _bill_product_lines(self, bill):
        return bill.invoice_line_ids.filtered(
            lambda line: (
                line.product_id
                and line.move_id.move_type == 'in_invoice'
                and line.display_type not in ('line_section', 'line_note')
            )
        )

    def check(self, bill):
        bill.ensure_one()
        bill_count = self.config.get_bill_count()
        comparison_mode = self.config.get_comparison_mode()
        no_history_policy_name = self.config.get_no_history_policy()
        comparison_policy = self.comparison_policy or HistoricalComparisonPolicy(comparison_mode)
        no_history_policy = self.no_history_policy or NoHistoryPolicy(no_history_policy_name)

        _logger.info(
            '%s start bill_id=%s bill=%s vendor_id=%s commercial_vendor_id=%s '
            'company_id=%s bill_count=%s comparison_mode=%s no_history_policy=%s',
            PRICE_CHECK_LOG_HEAD,
            bill.id,
            bill.name or 'Unnamed',
            bill.partner_id.id,
            bill.partner_id.commercial_partner_id.id,
            bill.company_id.id,
            bill_count,
            comparison_mode,
            no_history_policy_name,
        )

        bill.discrepancy_ids.unlink()
        if not bill_count:
            return []

        discrepancies = []
        for line in self._bill_product_lines(bill):
            current_price = self.calculator.calculate(line)
            history = self.repository.find_prices(line, bill_count)
            if not history:
                discrepancies.extend(no_history_policy.apply(bill, line))
                continue

            comparison = comparison_policy.compare(current_price, history)
            _logger.info(
                '%s compared bill_id=%s line_id=%s product_id=%s current_final_unit_incl=%s '
                'lowest=%s average=%s diff_lowest=%s diff_average=%s is_discrepancy=%s',
                PRICE_CHECK_LOG_HEAD,
                bill.id,
                line.id,
                line.product_id.id,
                current_price,
                comparison['lowest_price'],
                comparison['average_price'],
                comparison['price_difference_lowest'],
                comparison['price_difference_average'],
                comparison['is_discrepancy'],
            )
            if comparison['is_discrepancy']:
                discrepancies.append(
                    self.recorder.create(bill, line, current_price, comparison).id
                )

        _logger.info(
            '%s complete bill_id=%s discrepancy_count=%s discrepancy_ids=%s',
            PRICE_CHECK_LOG_HEAD,
            bill.id,
            len(discrepancies),
            discrepancies,
        )
        return discrepancies
