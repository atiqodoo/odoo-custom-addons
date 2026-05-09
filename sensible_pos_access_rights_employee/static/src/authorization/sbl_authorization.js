/** @odoo-module */
/* global Sha1 */

import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { sblGetAction } from "@sensible_pos_access_rights_employee/authorization/sbl_action_registry";

const LOG_PREFIX = "[SBL POS AUTH]";

export function sblDebug(...args) {
    console.debug(LOG_PREFIX, ...args);
}

export function sblInfo(...args) {
    console.info(LOG_PREFIX, ...args);
}

export function sblWarn(...args) {
    console.warn(LOG_PREFIX, ...args);
}

export function sblError(...args) {
    console.error(LOG_PREFIX, ...args);
}

export function sblIsActionRestricted(pos, actionKey, options = {}) {
    const cashier = pos.get_cashier?.();
    const action = sblGetAction(actionKey);
    if (!cashier || !action.field) {
        return false;
    }
    if (actionKey === "payment_method") {
        const paymentMethodId = options.paymentMethod?.id || options.paymentMethodId;
        const disabledMethods = cashier.sbl_disabled_payment_method_ids || [];
        return Boolean(paymentMethodId && disabledMethods.some((method) => method.id === paymentMethodId));
    }
    return Boolean(cashier[action.field]);
}

export async function sblAuthorizeAction(pos, dialog, notification, actionKey, options = {}) {
    const action = sblGetAction(actionKey);
    const cashier = pos.get_cashier?.();
    const actionLabel = options.label || action.label || actionKey;

    if (!sblIsActionRestricted(pos, actionKey, options)) {
        sblDebug("action allowed without authorization", { actionKey, cashierId: cashier?.id });
        return true;
    }

    sblInfo("authorization requested", { actionKey, actionLabel, cashierId: cashier?.id });
    const pin = await makeAwaitable(dialog, NumberPopup, {
        title: _t("Supervisor Authorization"),
        subtitle: _t("Enter supervisor PIN for: %s", actionLabel),
        formatDisplayedValue: (value) => String(value || "").replace(/./g, "*"),
        placeholder: _t("PIN"),
        confirmButtonLabel: _t("Authorize"),
    });

    if (!pin) {
        sblWarn("authorization cancelled", { actionKey, cashierId: cashier?.id });
        return false;
    }

    const order = pos.get_order?.();
    const payload = [
        pin,
        actionKey,
        cashier?.id || false,
        pos.config?.id || false,
        pos.session?.id || false,
        order?.pos_reference || order?.name || false,
        actionLabel,
    ];

    try {
        const result = await pos.data.call(
            "hr.employee",
            "sbl_validate_pos_supervisor_authorization",
            payload
        );
        if (result?.approved) {
            sblInfo("authorization approved by backend", {
                actionKey,
                cashierId: cashier?.id,
                supervisorId: result.supervisor_id,
            });
            notification?.add(_t("Authorization approved."), { type: "success" });
            return true;
        }
        sblWarn("authorization denied by backend", {
            actionKey,
            cashierId: cashier?.id,
            message: result?.message,
        });
        dialog.add(AlertDialog, {
            title: _t("Authorization Denied"),
            body: result?.message || _t("Invalid supervisor PIN."),
        });
        return false;
    } catch (error) {
        sblError("backend authorization failed; trying local PIN fallback", error);
        const localSupervisor = sblFindLocalSupervisorByPin(pos, pin);
        if (localSupervisor) {
            notification?.add(
                _t("Authorization approved locally. Backend log could not be written."),
                { type: "warning" }
            );
            sblWarn("authorization approved locally without backend log", {
                actionKey,
                cashierId: cashier?.id,
                supervisorId: localSupervisor.id,
            });
            return true;
        }
        dialog.add(AlertDialog, {
            title: _t("Authorization Error"),
            body: _t("Could not validate the supervisor PIN. Please check the PIN or connection."),
        });
        return false;
    }
}

export async function sblGuardedAction(pos, dialog, notification, actionKey, callback, options = {}) {
    if (await sblAuthorizeAction(pos, dialog, notification, actionKey, options)) {
        return await callback();
    }
    return false;
}

function sblFindLocalSupervisorByPin(pos, pin) {
    const hashedPin = Sha1?.hash ? Sha1.hash(pin) : false;
    if (!hashedPin) {
        return false;
    }
    return pos.models["hr.employee"].find(
        (employee) => employee._pin === hashedPin && employee._role === "manager"
    );
}
