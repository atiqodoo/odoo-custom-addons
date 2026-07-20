import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { DiscountTypePopup } from "@pos_fixed_discount/js/discount_type_popup";
import { CodOrdersScreen } from "@pos_cod/app/screens/cod_orders_screen/CodOrdersScreen";
import { codWarn, codError } from "@pos_cod/app/utils/cod_logger";

const COMPONENT = "CodDiscountPatch";

patch(CodOrdersScreen.prototype, {
    async onCodDiscount(order) {
        const orderId = this.orderServerId(order);
        const openAmount = this.openAmount(order);

        codWarn(COMPONENT, "onCodDiscount", "Discount requested", {
            orderId,
            orderRef: order.name || order.pos_reference,
            openAmount,
            paid: this.paidAmount(order),
            returned: this.returnedAmount(order),
        });

        if (!orderId || openAmount <= 0) {
            this.dialog.add(AlertDialog, {
                title: _t("COD Discount Unavailable"),
                body: _t("This COD order has no open receivable to discount."),
            });
            return;
        }

        while (true) {
            const payload = await makeAwaitable(this.dialog, DiscountTypePopup, {
                title: _t("COD Discount"),
                startingValue: "",
                defaultType: "fixed",
            });

            if (!payload) {
                codWarn(COMPONENT, "onCodDiscount", "Cashier cancelled discount popup", { orderId });
                return;
            }

            const parsed = parseFloat(payload.value?.toString() || "");
            if (isNaN(parsed) || parsed <= 0) {
                this.dialog.add(AlertDialog, {
                    title: _t("Invalid Discount"),
                    body: _t("Enter a discount greater than zero."),
                });
                continue;
            }

            const discountAmount =
                payload.type === "percentage"
                    ? Math.min(100, Math.max(0, parsed)) * openAmount / 100
                    : parsed;

            codWarn(COMPONENT, "onCodDiscount", "Submitting discount", {
                orderId,
                type: payload.type,
                rawValue: parsed,
                discountAmount,
                openAmount,
            });

            const result = await this._applyCodDiscount(order, discountAmount);
            if (result?.success) {
                this.state.message = `${result.order_name}: discount applied (${this.formatCurrency(result.amount)}).`;
                this.state.messageType = "success";
                if (!result.remaining) {
                    this.state.selectedOrderId = null;
                }
                await this.pos.cod_fetch_pending_orders();
                return;
            }

            const message = result?.message || _t("The discount could not be applied.");
            codWarn(COMPONENT, "onCodDiscount", "Discount blocked", {
                orderId,
                result,
            });
            await this._showCodDiscountWarning(message, result);
        }
    },

    async _applyCodDiscount(order, amount) {
        try {
            const result = await this.pos.data.call(
                "pos.order",
                "apply_cod_discount",
                [{
                    order_id: this.orderServerId(order),
                    order_ref: order.name || order.pos_reference,
                    session_id: this.pos.session?.id,
                    amount,
                }]
            );
            codWarn(COMPONENT, "_applyCodDiscount", "Backend response", result);
            return result;
        } catch (err) {
            codError(COMPONENT, "_applyCodDiscount", err?.message || err);
            return {
                success: false,
                message: _t("Network/server error while applying COD discount. Please try again."),
            };
        }
    },

    _showCodDiscountWarning(message, result = {}) {
        const details = [];
        if (result.open_amount !== undefined) {
            details.push(_t("Open receivable") + `: ${this.formatCurrency(result.open_amount)}`);
        }
        if (result.remaining_profit !== undefined) {
            details.push(_t("Remaining profit") + `: ${this.formatCurrency(result.remaining_profit)}`);
        }
        if (result.amount !== undefined) {
            details.push(_t("Requested discount") + `: ${this.formatCurrency(result.amount)}`);
        }

        return new Promise((resolve) => {
            this.dialog.add(AlertDialog, {
                title: _t("Discount Blocked"),
                body: [message, ...details, _t("Enter a smaller discount amount.")].join("\n"),
                confirm: resolve,
                cancel: resolve,
                dismiss: resolve,
            });
        });
    },
});
