/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";


const activePromotionWarnings = new Set();


async function promotionWarningAction(env, action) {
    const params = action.params || {};
    const { log_id: logId, fingerprint } = params;
    const warningKey = `${logId}:${fingerprint}`;

    if (activePromotionWarnings.has(warningKey)) {
        console.info("[VPP_CHECKER_JS] duplicate promotion warning suppressed", {
            logId,
            fingerprint,
        });
        return;
    }
    activePromotionWarnings.add(warningKey);

    console.warn("[VPP_CHECKER_JS] showing promotion warning", {
        logId,
        dismissalCount: params.dismissal_count,
        fingerprint,
    });

    let closeWarning;
    closeWarning = env.services.notification.add(params.message || _t("Promotion opportunity found."), {
        title: params.title || _t("Promotion Available — Confirmation Paused"),
        type: "warning",
        sticky: true,
        className: "o_vendor_promotion_checker_warning",
        buttons: [
            {
                name: _t("Dismiss"),
                icon: "fa-times",
                primary: true,
                onClick: () => {
                    console.info("[VPP_CHECKER_JS] explicit dismiss button clicked", {
                        logId,
                        fingerprint,
                    });
                    closeWarning();
                },
            },
        ],
        onClose: async () => {
            activePromotionWarnings.delete(warningKey);
            console.info("[VPP_CHECKER_JS] warning closed; registering dismissal", {
                logId,
                fingerprint,
            });
            try {
                const result = await env.services.orm.call(
                    "vendor.promotion.override.log",
                    "action_register_dismissal",
                    [[logId], fingerprint]
                );
                console.info("[VPP_CHECKER_JS] dismissal registered", result);
                if (result.override_available) {
                    env.services.notification.add(
                        _t("Override enabled. Click Confirm Order again to confirm this LPO with the quoted quantities."),
                        {
                            title: _t("Promotion Override Ready"),
                            type: "danger",
                            sticky: false,
                            autocloseDelay: 8000,
                        }
                    );
                } else if (!result.ignored) {
                    env.services.notification.add(
                        _t("Promotion warning dismissed once. Confirm again to review the opportunity a second time."),
                        {
                            title: _t("First Dismissal Recorded"),
                            type: "info",
                            sticky: false,
                            autocloseDelay: 6000,
                        }
                    );
                }
            } catch (error) {
                activePromotionWarnings.delete(warningKey);
                console.error("[VPP_CHECKER_JS] failed to register dismissal", {
                    logId,
                    fingerprint,
                    error,
                });
                env.services.notification.add(
                    _t("The dismissal could not be recorded. Please confirm again and close the new warning."),
                    {
                        title: _t("Promotion Checker Error"),
                        type: "danger",
                        sticky: true,
                    }
                );
            }
        },
    });
}


registry.category("actions").add(
    "vendor_purchase_promotions.promotion_warning",
    promotionWarningAction
);
