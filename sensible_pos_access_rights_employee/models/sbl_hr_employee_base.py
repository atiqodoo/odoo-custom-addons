# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
from odoo import fields, models, _


class HrEmployeeBase(models.AbstractModel):
    _inherit = 'hr.employee.base'
    sbl_hide_pos_new_order_button = fields.Boolean(
        string='Require Authorization for New Order',
        help='If checked, this employee needs supervisor authorization before creating a new POS order.',
        default=False,
    )
    sbl_hide_pos_delete_order_button = fields.Boolean(
        string='Require Authorization for Delete Order',
        help='If checked, this employee needs supervisor authorization before deleting a POS order.',
        default=False,
    )
    sbl_hide_pos_customer_selection_button = fields.Boolean(
        string='Require Authorization for Customer Selection',
        help='If checked, this employee needs supervisor authorization before selecting a customer.',
        default=False,
    )
    sbl_hide_pos_actions_button = fields.Boolean(
        string='Require Authorization for Actions',
        help='If checked, this employee needs supervisor authorization before opening POS actions.',
        default=False,
    )
    sbl_hide_pos_numpad = fields.Boolean(
        string='Require Authorization for Numpad',
        help='If checked, this employee needs supervisor authorization before using the POS numpad.',
        default=False,
    )
    sbl_disable_pos_numpad_plus_minus = fields.Boolean(
        string='Require Authorization for Plus-Minus Buttons',
        help='If checked, this employee needs supervisor authorization before using the Plus-Minus button.',
        default=False,
    )
    sbl_disable_pos_qty = fields.Boolean(
        string='Require Authorization for Quantity (QTY)',
        help='If checked, this employee needs supervisor authorization before changing quantity.',
        default=False,
    )
    sbl_disable_pos_discount_button = fields.Boolean(
        string='Require Authorization for Discount',
        help='If checked, this employee needs supervisor authorization before applying discounts.',
        default=False,
    )
    sbl_require_auth_global_discount = fields.Boolean(
        string='Require Authorization for Global Discount',
        help='If checked, this employee needs supervisor authorization before using the POS Global Discount button.',
        default=False,
    )
    sbl_require_auth_cod_dispatch = fields.Boolean(
        string='Require Authorization for COD',
        help='If checked, this employee needs supervisor authorization before dispatching a COD order.',
        default=False,
    )
    sbl_require_auth_cod_pay_all = fields.Boolean(
        string='Require Authorization for COD Full Pay',
        help='If checked, this employee needs supervisor authorization before receiving full COD payment.',
        default=False,
    )
    sbl_require_auth_cod_pay_partial = fields.Boolean(
        string='Require Authorization for COD Partial Pay',
        help='If checked, this employee needs supervisor authorization before receiving partial COD payment.',
        default=False,
    )
    sbl_require_auth_cod_return_all = fields.Boolean(
        string='Require Authorization for COD Return All',
        help='If checked, this employee needs supervisor authorization before returning a full COD order.',
        default=False,
    )
    sbl_require_auth_cod_return_partial = fields.Boolean(
        string='Require Authorization for COD Partial Return',
        help='If checked, this employee needs supervisor authorization before returning part of a COD order.',
        default=False,
    )
    sbl_require_auth_cod_discount = fields.Boolean(
        string='Require Authorization for COD Discount',
        help='If checked, this employee needs supervisor authorization before applying a discount on a pending COD order.',
        default=False,
    )
    sbl_hide_pos_payment = fields.Boolean(
        string='Require Authorization for Payment',
        help='If checked, this employee needs supervisor authorization before opening payment.',
        default=False,
    )
    sbl_disable_pos_change_price = fields.Boolean(
        string='Require Authorization for Change Price',
        help='If checked, this employee needs supervisor authorization before changing price.',
        default=False,
    )
    sbl_hide_pos_finance_from_product_info = fields.Boolean(
        string='Require Authorization for Product Info Financials',
        help='If checked, this employee needs supervisor authorization for product information financial details.',
        default=False,
    )
    sbl_hide_pos_cash_in_out = fields.Boolean(
        string='Require Authorization for Cash In/Out',
        help='If checked, this employee needs supervisor authorization before Cash In/Out.',
        default=False,
    )
    sbl_hide_pos_create_customer_button = fields.Boolean(
        string='Require Authorization for Create Customer',
        help='If checked, this employee needs supervisor authorization before creating customers.',
        default=False,
    )
    sbl_hide_pos_edit_customer_button = fields.Boolean(
        string='Require Authorization for Edit Customer',
        help='If checked, this employee needs supervisor authorization before editing customers.',
        default=False,
    )
    sbl_hide_pos_payment_customer_button = fields.Boolean(
        string='Require Authorization for Payment Customer',
        help='If checked, this employee needs supervisor authorization before changing the customer on payment.',
        default=False,
    )
    sbl_hide_pos_payment_invoice_button = fields.Boolean(
        string='Require Authorization for Invoice',
        help='If checked, this employee needs supervisor authorization before toggling invoice.',
        default=False,
    )
    sbl_hide_pos_payment_validate_button = fields.Boolean(
        string='Require Authorization for Validate',
        help='If checked, this employee needs supervisor authorization before validating payment.',
        default=False,
    )
    sbl_hide_pos_payment_ship_later_button = fields.Boolean(
        string='Require Authorization for Ship Later',
        help='If checked, this employee needs supervisor authorization before using Ship Later.',
        default=False,
    )
    sbl_hide_pos_tip_button = fields.Boolean(
        string='Require Authorization for Tip',
        help='If checked, this employee needs supervisor authorization before adding or changing tips.',
        default=False,
    )
    sbl_hide_pos_open_cashbox_button = fields.Boolean(
        string='Require Authorization for Open Cashbox',
        help='If checked, this employee needs supervisor authorization before opening the cashbox.',
        default=False,
    )
    sbl_disabled_payment_method_ids = fields.Many2many(
        'pos.payment.method',
        'sbl_hr_employee_disabled_payment_method_rel',
        'employee_id',
        'payment_method_id',
        string='Payment Methods Requiring Authorization',
        help='Payment methods that require supervisor authorization for this employee.',
    )
    sbl_deposit_settle_payment_method_ids = fields.Many2many(
        'pos.payment.method',
        'sbl_hr_employee_deposit_settle_payment_method_rel',
        'employee_id',
        'payment_method_id',
        string='Deposit / Due Settlement Payment Methods Requiring Authorization',
        help='Payment methods that require supervisor authorization when receiving customer deposits or settling due amounts.',
    )
    sbl_hide_pos_install_app = fields.Boolean(
        string='Require Authorization for Install App',
        help='If checked, this employee needs supervisor authorization before using Install App.',
        default=False,
    )
    sbl_hide_pos_orders_menu = fields.Boolean(
        string='Require Authorization for Orders Menu',
        help='If checked, this employee needs supervisor authorization before opening Orders.',
        default=False,
    )
    sbl_hide_pos_backend_menu = fields.Boolean(
        string='Require Authorization for Backend Menu',
        help='If checked, this employee needs supervisor authorization before going to Backend.',
        default=False,
    )
    sbl_hide_pos_close_register = fields.Boolean(
        string='Require Authorization for Close Register',
        help='If checked, this employee needs supervisor authorization before closing the register.',
        default=False,
    )
    sbl_hide_pos_daily_sale = fields.Boolean(
        string='Require Authorization for Daily Sale',
        help='If checked, this employee needs supervisor authorization before downloading the Daily Sale report.',
        default=False,
    )
    sbl_hide_pos_clear_cache = fields.Boolean(
        string='Require Authorization for Clear Cache',
        help='If checked, this employee needs supervisor authorization before clearing cache.',
        default=False,
    )
    sbl_hide_pos_debug_window = fields.Boolean(
        string='Require Authorization for Debug Window',
        help='If checked, this employee needs supervisor authorization before opening the debug window.',
        default=False,
    )
    sbl_block_mpesa_sms_app = fields.Boolean(
        string='Block M-Pesa SMS App',
        help='If checked, this employee cannot open the M-Pesa SMS backend app.',
        default=False,
    )

    # POS Actions Popup - Base Actions
    sbl_hide_pos_action_general_note = fields.Boolean(
        string='Require Authorization for General Note',
        help='If checked, this employee needs supervisor authorization before editing the general note.',
        default=False,
    )
    sbl_hide_pos_action_customer_note = fields.Boolean(
        string='Require Authorization for Customer Note',
        help='If checked, this employee needs supervisor authorization before editing the customer note.',
        default=False,
    )
    sbl_hide_pos_action_pricelist = fields.Boolean(
        string='Require Authorization for Pricelist',
        help='If checked, this employee needs supervisor authorization before changing pricelist.',
        default=False,
    )
    sbl_hide_pos_action_refund = fields.Boolean(
        string='Require Authorization for Refund',
        help='If checked, this employee needs supervisor authorization before starting a refund.',
        default=False,
    )
    sbl_hide_pos_action_reward = fields.Boolean(
        string='Require Authorization for Reward',
        help='If checked, this employee needs supervisor authorization before applying rewards.',
        default=False,
    )
    sbl_hide_pos_action_fiscal_position = fields.Boolean(
        string='Require Authorization for Fiscal Position',
        help='If checked, this employee needs supervisor authorization before changing fiscal position or tax.',
        default=False,
    )
    sbl_hide_pos_action_cancel_order = fields.Boolean(
        string='Require Authorization for Cancel Order',
        help='If checked, this employee needs supervisor authorization before cancelling an order.',
        default=False,
    )
    sbl_hide_pos_action_product_info = fields.Boolean(
        string='Require Authorization for Product Info',
        help='If checked, this employee needs supervisor authorization before opening product info.',
        default=False,
    )
    sbl_require_auth_team_kubwa_open = fields.Boolean(
        string='Require Authorization for Team Kubwa',
        help='If checked, this employee needs supervisor authorization before opening Team Kubwa.',
        default=False,
    )
    sbl_require_auth_team_kubwa_create_customer = fields.Boolean(
        string='Require Authorization for Team Kubwa Customer Creation',
        help='If checked, this employee needs supervisor authorization before creating a Team Kubwa customer.',
        default=False,
    )
    sbl_require_auth_team_kubwa_check_eligibility = fields.Boolean(
        string='Require Authorization for Team Kubwa Eligibility Check',
        help='If checked, this employee needs supervisor authorization before checking Team Kubwa eligibility.',
        default=False,
    )
    sbl_require_auth_team_kubwa_save_draft = fields.Boolean(
        string='Require Authorization for Team Kubwa Draft Save',
        help='If checked, this employee needs supervisor authorization before manually saving a Team Kubwa draft.',
        default=False,
    )
    sbl_require_auth_team_kubwa_open_draft = fields.Boolean(
        string='Require Authorization for Team Kubwa Draft Open',
        help='If checked, this employee needs supervisor authorization before opening a Team Kubwa draft.',
        default=False,
    )
    sbl_require_auth_team_kubwa_continue_otp = fields.Boolean(
        string='Require Authorization for Team Kubwa Continue to OTP',
        help='If checked, this employee needs supervisor authorization before moving a Team Kubwa cash-out to OTP.',
        default=False,
    )
    sbl_require_auth_team_kubwa_mark_otp = fields.Boolean(
        string='Require Authorization for Team Kubwa OTP Confirmation',
        help='If checked, this employee needs supervisor authorization before marking Team Kubwa OTP received.',
        default=False,
    )
    sbl_require_auth_team_kubwa_continue_pay = fields.Boolean(
        string='Require Authorization for Team Kubwa Continue to Pay',
        help='If checked, this employee needs supervisor authorization before moving a Team Kubwa cash-out to Pay.',
        default=False,
    )
    sbl_require_auth_team_kubwa_manager_override = fields.Boolean(
        string='Require Authorization for Team Kubwa Manager Override',
        help='If checked, this employee needs supervisor authorization before using Team Kubwa manager override.',
        default=False,
    )
    sbl_require_auth_team_kubwa_pay_post = fields.Boolean(
        string='Require Authorization for Team Kubwa Pay & Post',
        help='If checked, this employee needs supervisor authorization before paying and posting a Team Kubwa cash-out.',
        default=False,
    )
