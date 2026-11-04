/** @odoo-module **/
import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";

// A UI refresh interval, independent of the editable overdue-check scheduled action.
const REFRESH_MS = 60_000;

registry.category("services").add("purchase_overdue_receipt_warning", {
    dependencies: ["orm", "action", "notification"],
    async start(env, { orm, action, notification }) {
        if (!(await user.hasGroup("purchase.group_purchase_user"))) {
            return;
        }
        const seen = new Set();
        let busy = false;
        async function check() {
            if (busy || document.hidden) {
                return;
            }
            busy = true;
            try {
                const warning = await orm.call("purchase.receipt.followup", "get_popup_warning", [[...seen]]);
                if (warning) {
                    seen.add(warning.id);
                    notification.add(warning.message, {
                        title: _t("Overdue Supplier Receipt"), type: "warning", sticky: true,
                        buttons: [{
                            name: _t("Review / Compare Stock"), primary: true,
                            onClick: async () => {
                                // The button endpoint prepares window actions (including views)
                                // before they reach the action service, just like XML object buttons.
                                await action.doActionButton({
                                    type: "object",
                                    name: "action_review",
                                    resModel: "purchase.receipt.followup",
                                    resId: warning.id,
                                    context: {},
                                });
                            },
                        }],
                    });
                }
            } catch (error) {
                // A failed poll must not interrupt the buyer or modify purchase state.
                console.debug("[OVERDUE_RECEIPT][WARNING_REFRESH][ERROR]", error.name);
            } finally {
                busy = false;
            }
        }
        // Defer until the web client has completed its initial action.
        browser.setTimeout(check, REFRESH_MS);
        browser.setInterval(check, REFRESH_MS);
    },
});
