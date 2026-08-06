/** @odoo-module **/
/**
 * credit_note_usage_guard.js
 *
 * Extra safety layer for the configured "Credit Note Gift Card" payment
 * method.  The method may only be used by the credit-note return flow; it is
 * blocked in COD collections and in POS customer deposit / due settlement.
 */

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { CodOrdersScreen } from "@pos_cod/app/screens/cod_orders_screen/CodOrdersScreen";

const LOG_PREFIX = "[CreditNoteUsageGuard]";

function log(message, payload = {}) {
    console.warn(LOG_PREFIX, message, payload);
}

function getPaymentMethodId(paymentMethod) {
    return Number(paymentMethod?.id || 0);
}

function getConfig(source) {
    return source?.config || source?.config_id || source || {};
}

function getCreditNotePaymentMethodId(source) {
    const raw = getConfig(source)?.credit_note_payment_method_id;
    return Number((raw && typeof raw === "object" ? raw.id : raw) || 0);
}

function isCreditNotePaymentMethod(pos, paymentMethod) {
    const configuredId = getCreditNotePaymentMethodId(pos);
    return Boolean(configuredId) && getPaymentMethodId(paymentMethod) === configuredId;
}

function orderLooksLikeCreditNoteReturn(order) {
    if (!order) {
        return false;
    }
    if (typeof order._isRefundOrder === "function" && order._isRefundOrder()) {
        return true;
    }
    const lines = order.get_orderlines?.() || order.lines || [];
    return lines.some((line) => {
        const qty = Number(line.qty ?? line.get_quantity?.() ?? 0);
        return qty < 0 || Boolean(line.refunded_orderline_id);
    });
}

function isCustomerDepositOrSettleOrder(order) {
    if (!order) {
        return false;
    }
    const partner = order.get_partner?.() || order.partner_id || order.partner;
    const lines = order.get_orderlines?.() || order.lines || [];
    return Boolean(partner) && lines.length === 0;
}

function blockMessage() {
    return _t(
        "This payment method is only used in creating credit notes. " +
        "It cannot be used for COD payment, customer deposit, due settlement, or a regular POS sale."
    );
}

function showBlockedDialog(dialog, context, paymentMethod, extra = {}) {
    log("BLOCKED credit-note payment method outside credit-note flow.", {
        context,
        paymentMethodId: paymentMethod?.id,
        paymentMethodName: paymentMethod?.name,
        ...extra,
    });
    dialog?.add(AlertDialog, {
        title: _t("Credit Note Payment Only"),
        body: blockMessage(),
    });
}

function isSettleDuePopupTitle(title) {
    return String(title || "").toLowerCase().includes("settle the due");
}

patch(SelectionPopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.cnUsagePos = usePos();
        this.cnUsageDialog = useService("dialog");
    },

    cnIsBlockedSelectionItem(item) {
        if (!isSettleDuePopupTitle(this.props.title)) {
            return false;
        }
        return isCreditNotePaymentMethod(this.cnUsagePos, item?.item);
    },

    selectItem(itemId) {
        const item = (this.props.list || []).find((entry) => entry.id === itemId);
        if (this.cnIsBlockedSelectionItem(item)) {
            showBlockedDialog(this.cnUsageDialog, "customer_deposit_or_due_popup", item.item, {
                popupTitle: this.props.title,
            });
            return;
        }
        return super.selectItem(...arguments);
    },
});

patch(CodOrdersScreen.prototype, {
    get creditNotePaymentMethodId() {
        return getCreditNotePaymentMethodId(this.pos);
    },

    get paymentMethods() {
        const methods = super.paymentMethods || [];
        const configuredId = this.creditNotePaymentMethodId;
        const filtered = configuredId
            ? methods.filter((method) => Number(method.id) !== configuredId)
            : methods;
        if (configuredId && methods.length !== filtered.length) {
            log("Hidden credit-note payment method from COD method selector.", {
                configuredId,
                hiddenCount: methods.length - filtered.length,
            });
        }
        return filtered;
    },

    onSelectPaymentMethod(ev) {
        const selectedId = Number(ev.target.value || 0);
        if (selectedId && selectedId === this.creditNotePaymentMethodId) {
            this.state.paymentMethodId = null;
            ev.target.value = "";
            showBlockedDialog(this.dialog, "cod_selector", { id: selectedId });
            return;
        }
        return super.onSelectPaymentMethod(...arguments);
    },

    async processCod(order, action, amount, returnLines = null) {
        if (
            this.state.paymentMethodId &&
            Number(this.state.paymentMethodId) === this.creditNotePaymentMethodId
        ) {
            this.state.message = _t("Credit Note Gift Card cannot be used for COD collection.");
            this.state.messageType = "error";
            showBlockedDialog(this.dialog, "cod_process", { id: this.state.paymentMethodId }, {
                order: order?.name,
                action,
                amount,
            });
            return;
        }
        return await super.processCod(...arguments);
    },
});

patch(PosStore.prototype, {
    async cod_collect_payment(orderId, paymentMethodId, amount) {
        if (Number(paymentMethodId || 0) === getCreditNotePaymentMethodId(this)) {
            log("Blocked COD RPC before server call.", { orderId, paymentMethodId, amount });
            return {
                success: false,
                message: _t("Credit Note Gift Card is only used in creating credit notes."),
            };
        }
        return await super.cod_collect_payment(...arguments);
    },
});

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        const order = this.currentOrder;
        const isCreditNoteMethod = isCreditNotePaymentMethod(this.pos, paymentMethod);
        const isAllowedCreditNoteReturn = orderLooksLikeCreditNoteReturn(order);

        if (isCreditNoteMethod && !isAllowedCreditNoteReturn) {
            showBlockedDialog(this.dialog, "payment_screen_add_line", paymentMethod, {
                order: order?.name || order?.uuid,
                isCod: Boolean(order?.is_cod),
                codState: order?.cod_state,
                isCustomerDepositOrSettle: isCustomerDepositOrSettleOrder(order),
            });
            return false;
        }
        return await super.addNewPaymentLine(...arguments);
    },
});

patch(PosOrder.prototype, {
    add_paymentline(paymentMethod) {
        if (
            isCreditNotePaymentMethod(this.config_id, paymentMethod) &&
            !orderLooksLikeCreditNoteReturn(this)
        ) {
            log("Low-level add_paymentline blocked.", {
                order: this.name || this.uuid,
                paymentMethodId: paymentMethod?.id,
                paymentMethodName: paymentMethod?.name,
                isCustomerDepositOrSettle: isCustomerDepositOrSettleOrder(this),
            });
            return false;
        }
        return super.add_paymentline(...arguments);
    },
});
