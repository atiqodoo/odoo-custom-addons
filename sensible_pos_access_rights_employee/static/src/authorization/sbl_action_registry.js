/** @odoo-module */

export const SBL_POS_ACTIONS = {
    new_order: {
        label: "New Order",
        field: "sbl_hide_pos_new_order_button",
    },
    delete_order: {
        label: "Delete Order",
        field: "sbl_hide_pos_delete_order_button",
    },
    select_customer: {
        label: "Select Customer",
        field: "sbl_hide_pos_customer_selection_button",
    },
    create_customer: {
        label: "Create Customer",
        field: "sbl_hide_pos_create_customer_button",
    },
    edit_customer: {
        label: "Edit Customer",
        field: "sbl_hide_pos_edit_customer_button",
    },
    actions_menu: {
        label: "Actions",
        field: "sbl_hide_pos_actions_button",
    },
    payment: {
        label: "Payment",
        field: "sbl_hide_pos_payment",
    },
    numpad: {
        label: "Numpad",
        field: "sbl_hide_pos_numpad",
    },
    numpad_plus_minus: {
        label: "Plus / Minus",
        field: "sbl_disable_pos_numpad_plus_minus",
    },
    qty: {
        label: "Quantity",
        field: "sbl_disable_pos_qty",
    },
    discount: {
        label: "Discount",
        field: "sbl_disable_pos_discount_button",
    },
    global_discount: {
        label: "Global Discount",
        field: "sbl_require_auth_global_discount",
    },
    cod_dispatch: {
        label: "COD",
        field: "sbl_require_auth_cod_dispatch",
    },
    cod_pay_all: {
        label: "COD Full Pay",
        field: "sbl_require_auth_cod_pay_all",
    },
    cod_pay_partial: {
        label: "COD Partial Pay",
        field: "sbl_require_auth_cod_pay_partial",
    },
    cod_return_all: {
        label: "COD Return All",
        field: "sbl_require_auth_cod_return_all",
    },
    cod_return_partial: {
        label: "COD Partial Return",
        field: "sbl_require_auth_cod_return_partial",
    },
    cod_discount: {
        label: "COD Discount",
        field: "sbl_require_auth_cod_discount",
    },
    change_price: {
        label: "Change Price",
        field: "sbl_disable_pos_change_price",
    },
    product_info: {
        label: "Product Info",
        field: "sbl_hide_pos_action_product_info",
    },
    product_info_financials: {
        label: "Product Info Financials",
        field: "sbl_hide_pos_finance_from_product_info",
    },
    payment_customer: {
        label: "Payment Customer",
        field: "sbl_hide_pos_payment_customer_button",
    },
    payment_invoice: {
        label: "Invoice",
        field: "sbl_hide_pos_payment_invoice_button",
    },
    payment_validate: {
        label: "Validate Payment",
        field: "sbl_hide_pos_payment_validate_button",
    },
    payment_ship_later: {
        label: "Ship Later",
        field: "sbl_hide_pos_payment_ship_later_button",
    },
    payment_tip: {
        label: "Tip",
        field: "sbl_hide_pos_tip_button",
    },
    open_cashbox: {
        label: "Open Cashbox",
        field: "sbl_hide_pos_open_cashbox_button",
    },
    payment_method: {
        label: "Payment Method",
        field: "sbl_disabled_payment_method_ids",
    },
    deposit_settle_payment_method: {
        label: "Deposit / Due Settlement Payment Method",
        field: "sbl_deposit_settle_payment_method_ids",
    },
    install_app: {
        label: "Install App",
        field: "sbl_hide_pos_install_app",
    },
    orders_menu: {
        label: "Orders",
        field: "sbl_hide_pos_orders_menu",
    },
    backend_menu: {
        label: "Backend",
        field: "sbl_hide_pos_backend_menu",
    },
    close_register: {
        label: "Close Register",
        field: "sbl_hide_pos_close_register",
    },
    daily_sale: {
        label: "Daily Sale",
        field: "sbl_hide_pos_daily_sale",
    },
    clear_cache: {
        label: "Clear Cache",
        field: "sbl_hide_pos_clear_cache",
    },
    debug_window: {
        label: "Debug Window",
        field: "sbl_hide_pos_debug_window",
    },
    cash_in_out: {
        label: "Cash In / Out",
        field: "sbl_hide_pos_cash_in_out",
    },
    general_note: {
        label: "General Note",
        field: "sbl_hide_pos_action_general_note",
    },
    customer_note: {
        label: "Customer Note",
        field: "sbl_hide_pos_action_customer_note",
    },
    pricelist: {
        label: "Pricelist",
        field: "sbl_hide_pos_action_pricelist",
    },
    refund: {
        label: "Refund",
        field: "sbl_hide_pos_action_refund",
    },
    reward: {
        label: "Reward",
        field: "sbl_hide_pos_action_reward",
    },
    fiscal_position: {
        label: "Fiscal Position",
        field: "sbl_hide_pos_action_fiscal_position",
    },
    cancel_order: {
        label: "Cancel Order",
        field: "sbl_hide_pos_action_cancel_order",
    },
    team_kubwa_open: {
        label: "Team Kubwa",
        field: "sbl_require_auth_team_kubwa_open",
    },
    team_kubwa_create_customer: {
        label: "Team Kubwa Create Customer",
        field: "sbl_require_auth_team_kubwa_create_customer",
    },
    team_kubwa_check_eligibility: {
        label: "Team Kubwa Check Eligibility",
        field: "sbl_require_auth_team_kubwa_check_eligibility",
    },
    team_kubwa_save_draft: {
        label: "Team Kubwa Save Draft",
        field: "sbl_require_auth_team_kubwa_save_draft",
    },
    team_kubwa_open_draft: {
        label: "Team Kubwa Open Draft",
        field: "sbl_require_auth_team_kubwa_open_draft",
    },
    team_kubwa_continue_otp: {
        label: "Team Kubwa Continue to OTP",
        field: "sbl_require_auth_team_kubwa_continue_otp",
    },
    team_kubwa_mark_otp: {
        label: "Team Kubwa Mark OTP",
        field: "sbl_require_auth_team_kubwa_mark_otp",
    },
    team_kubwa_continue_pay: {
        label: "Team Kubwa Continue to Pay",
        field: "sbl_require_auth_team_kubwa_continue_pay",
    },
    team_kubwa_manager_override: {
        label: "Team Kubwa Manager Override",
        field: "sbl_require_auth_team_kubwa_manager_override",
    },
    team_kubwa_pay_post: {
        label: "Team Kubwa Pay & Post",
        field: "sbl_require_auth_team_kubwa_pay_post",
    },
};

export function sblGetAction(actionKey) {
    return SBL_POS_ACTIONS[actionKey] || {
        label: actionKey,
        field: false,
    };
}
