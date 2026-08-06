/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { CodOrdersScreen } from "@pos_cod/app/screens/cod_orders_screen/CodOrdersScreen";
import {
    isMpesaPaymentMethod,
    openMpesaPaymentDialog,
} from "../utils/mpesa_payment_dialog";

const LOG = "[M-Pesa POS][COD]";

function selectedPaymentMethod(screen) {
    return screen.paymentMethods.find((method) => method.id === screen.state.paymentMethodId);
}

patch(CodOrdersScreen.prototype, {
    async processCod(order, action, amount, returnLines = null) {
        const paymentMethod = selectedPaymentMethod(this);
        let mpesaRef = false;
        let appliedAmount = Number(amount || 0);

        console.warn(LOG, "processCod start", {
            order: order?.name,
            orderId: order?.id,
            serverId: order?.server_id,
            action,
            requestedAmount: amount,
            paymentMethod: paymentMethod?.name,
            paymentMethodId: paymentMethod?.id,
            is_mpesa: paymentMethod?.is_mpesa,
        });

        if (!isMpesaPaymentMethod(paymentMethod)) {
            console.warn(LOG, "non-M-Pesa COD method delegated to next guard", {
                order: order?.name,
                paymentMethod: paymentMethod?.name,
                paymentMethodId: paymentMethod?.id,
                action,
            });
            return await super.processCod(...arguments);
        }

        if (isMpesaPaymentMethod(paymentMethod) && action === "payment" && appliedAmount > 0) {
            const mpesaResult = await openMpesaPaymentDialog(this.dialog, {
                orderAmount: appliedAmount,
                posSessionId: this.pos.session?.id,
                context: "cod_collection",
            });
            if (!mpesaResult) {
                this.state.message = "M-Pesa validation cancelled. COD payment not posted.";
                this.state.messageType = "error";
                console.warn(LOG, "validation cancelled", {
                    order: order?.name,
                    amount: appliedAmount,
                });
                return;
            }
            mpesaRef = mpesaResult.mpesaRef;
            appliedAmount = Number(mpesaResult.amount || appliedAmount);
            console.warn(LOG, "validation accepted", {
                order: order?.name,
                mpesaRef,
                appliedAmount,
            });
        } else if (isMpesaPaymentMethod(paymentMethod) && action !== "payment") {
            console.warn(LOG, "M-Pesa selected for non-payment COD action; using normal COD return flow", {
                order: order?.name,
                action,
            });
        }

        if (!this.state.paymentMethodId) {
            this.state.message = "Please select a payment method first.";
            this.state.messageType = "error";
            return;
        }
        if (!appliedAmount || appliedAmount <= 0) {
            return;
        }

        this.state.collecting = true;
        this.state.message = "";
        try {
            const result = await this.pos.cod_collect_payment(
                this.orderServerId(order),
                this.state.paymentMethodId,
                appliedAmount,
                this.pos.session?.id,
                action,
                order.name || order.pos_reference,
                returnLines,
                mpesaRef
            );
            if (result.success) {
                const loyaltyIssued = (result.loyalty_points || []).reduce(
                    (sum, item) => sum + Number(item.issued || 0),
                    0
                );
                const loyaltyText = loyaltyIssued > 0
                    ? ` Loyalty +${loyaltyIssued.toFixed(2)} pts.`
                    : "";
                this.state.message = `${result.order_name}: ${action === "return" ? "return recorded" : "payment received"} (${this.formatCurrency(result.amount)}).${loyaltyText}`;
                this.state.messageType = "success";
                if (!result.remaining) {
                    this.state.selectedOrderId = null;
                }
                console.warn(LOG, "COD action completed", {
                    ...result,
                    mpesaRef,
                });
            } else {
                this.state.message = `Error: ${result.message}`;
                this.state.messageType = "error";
                console.error(LOG, "backend error", result);
            }
        } catch (err) {
            this.state.message = "Network error. Please try again.";
            this.state.messageType = "error";
            console.error(LOG, "RPC failed", err?.message || err);
        } finally {
            this.state.collecting = false;
        }
    },
});
