/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";


const activeSubstitutionWarnings = new Set();


async function substitutionMismatchWarningAction(env, action) {
    const params = action.params || {};
    const { log_id: logId, fingerprint } = params;
    const warningKey = `${logId}:${fingerprint}`;

    if (activeSubstitutionWarnings.has(warningKey)) {
        console.info("[VPP_SUBSTITUTE_JS] duplicate mismatch warning suppressed", {
            logId,
            fingerprint,
        });
        return;
    }
    activeSubstitutionWarnings.add(warningKey);

    console.warn("[VPP_SUBSTITUTE_JS] showing mismatch warning", {
        logId,
        dismissalCount: params.dismissal_count,
        fingerprint,
    });

    let closeWarning;
    closeWarning = env.services.notification.add(
        params.message || _t("FOC substitute UoM/category mismatch."),
        {
            title: params.title || _t("FOC Substitute Mismatch - Apply Paused"),
            type: "warning",
            sticky: true,
            className: "o_vendor_promotion_checker_warning",
            buttons: [
                {
                    name: _t("Dismiss"),
                    icon: "fa-times",
                    primary: true,
                    onClick: () => {
                        console.info("[VPP_SUBSTITUTE_JS] explicit dismiss button clicked", {
                            logId,
                            fingerprint,
                        });
                        closeWarning();
                    },
                },
            ],
            onClose: async () => {
                activeSubstitutionWarnings.delete(warningKey);
                console.info("[VPP_SUBSTITUTE_JS] warning closed; registering dismissal", {
                    logId,
                    fingerprint,
                });
                try {
                    const result = await env.services.orm.call(
                        "vendor.promotion.substitution.override.log",
                        "action_register_dismissal",
                        [[logId], fingerprint]
                    );
                    console.info("[VPP_SUBSTITUTE_JS] dismissal registered", result);
                    if (result.override_available) {
                        env.services.notification.add(
                            _t("Override enabled. Click Apply Substitute again to apply these mismatched FOC substitutes."),
                            {
                                title: _t("Substitute Override Ready"),
                                type: "danger",
                                sticky: false,
                                autocloseDelay: 8000,
                            }
                        );
                    } else if (!result.ignored) {
                        const remaining = Math.max(
                            (result.dismissal_limit || 3) - result.dismissal_count,
                            0
                        );
                        env.services.notification.add(
                            _t("Substitute warning dismissed. Remaining dismissals before override: %s", remaining),
                            {
                                title: _t("Dismissal Recorded"),
                                type: "info",
                                sticky: false,
                                autocloseDelay: 6000,
                            }
                        );
                    }
                } catch (error) {
                    activeSubstitutionWarnings.delete(warningKey);
                    console.error("[VPP_SUBSTITUTE_JS] failed to register dismissal", {
                        logId,
                        fingerprint,
                        error,
                    });
                    env.services.notification.add(
                        _t("The dismissal could not be recorded. Apply the substitute again and close the new warning."),
                        {
                            title: _t("Substitute Checker Error"),
                            type: "danger",
                            sticky: true,
                        }
                    );
                }
            },
        }
    );
}


registry.category("actions").add(
    "vendor_purchase_promotions.substitution_mismatch_warning",
    substitutionMismatchWarningAction
);
