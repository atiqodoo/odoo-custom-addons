/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

const MPESA_MENU_XMLID = "mpesa_c2b_sms.menu_mpesa_root";
const serviceRegistry = registry.category("services");
const menuServiceDefinition = serviceRegistry.get("menu");

function isMpesaMenu(menu, service) {
    if (!menu) {
        return false;
    }
    const app = service.getApps().find((candidate) => candidate.xmlid === MPESA_MENU_XMLID);
    return Boolean(app && (menu.id === app.id || menu.appID === app.id));
}

async function requestMpesaSmsAuthorization(orm) {
    const employeePin = window.prompt(_t("Enter employee PIN to open the M-Pesa SMS app."));
    if (!employeePin) {
        return false;
    }

    const login = await orm.call("hr.employee", "sbl_mpesa_sms_employee_login", [employeePin]);
    if (!login?.success) {
        window.alert(login?.message || _t("Invalid employee PIN."));
        return false;
    }
    if (!login.blocked) {
        return true;
    }

    const supervisorPin = window.prompt(
        _t(
            "%s is blocked from opening the M-Pesa SMS app.\nEnter supervisor PIN to authorize.",
            login.employee_name
        )
    );
    if (!supervisorPin) {
        return false;
    }

    const authorization = await orm.call("hr.employee", "sbl_mpesa_sms_supervisor_authorize", [
        supervisorPin,
        login.employee_id,
    ]);
    if (!authorization?.approved) {
        window.alert(authorization?.message || _t("Supervisor authorization denied."));
        return false;
    }
    return true;
}

serviceRegistry.add(
    "menu",
    {
        ...menuServiceDefinition,
        dependencies: Array.from(new Set([...(menuServiceDefinition.dependencies || []), "orm"])),
        async start(env, dependencies) {
            const service = await menuServiceDefinition.start(env, dependencies);
            const originalSelectMenu = service.selectMenu.bind(service);

            service.selectMenu = async function selectMenu(menu) {
                const resolvedMenu = typeof menu === "number" ? service.getMenu(menu) : menu;
                if (isMpesaMenu(resolvedMenu, service)) {
                    const allowed = await requestMpesaSmsAuthorization(dependencies.orm);
                    if (!allowed) {
                        return;
                    }
                }
                return originalSelectMenu(menu);
            };

            return service;
        },
    },
    { force: true }
);
