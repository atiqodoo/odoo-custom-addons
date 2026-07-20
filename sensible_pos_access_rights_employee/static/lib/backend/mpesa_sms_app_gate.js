/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

const MPESA_MENU_XMLID = "mpesa_c2b_sms.menu_mpesa_root";
const serviceRegistry = registry.category("services");
const menuServiceDefinition = serviceRegistry.get("menu");
let mpesaSmsAuthorized = false;
let mpesaSmsAuthorizedUntil = 0;
let mpesaSmsTimerConfig = null;
let mpesaSmsTimerConfigTimestamp = 0;

const MPESA_TIMER_CONFIG_TTL_MS = 5 * 60 * 1000;

function isMpesaMenu(menu, service) {
    if (!menu) {
        return false;
    }
    const app = service.getApps().find((candidate) => candidate.xmlid === MPESA_MENU_XMLID);
    return Boolean(app && (menu.id === app.id || menu.appID === app.id));
}

function showMpesaPinDialog(message) {
    return new Promise((resolve) => {
        const overlay = document.createElement("div");
        Object.assign(overlay.style, {
            position: "fixed",
            inset: "0",
            background: "rgba(0, 0, 0, 0.55)",
            zIndex: "10000",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
        });

        const card = document.createElement("div");
        Object.assign(card.style, {
            width: "420px",
            maxWidth: "calc(100vw - 32px)",
            background: "#fff",
            borderRadius: "8px",
            boxShadow: "0 14px 40px rgba(0, 0, 0, 0.28)",
            padding: "24px",
            fontFamily: "inherit",
        });

        const title = document.createElement("h3");
        title.textContent = _t("M-Pesa SMS Access");
        Object.assign(title.style, {
            margin: "0 0 10px",
            fontSize: "18px",
            fontWeight: "600",
            color: "#1f2933",
        });

        const body = document.createElement("p");
        body.textContent = message;
        Object.assign(body.style, {
            margin: "0 0 16px",
            fontSize: "14px",
            lineHeight: "1.45",
            color: "#374151",
        });

        const inputWrap = document.createElement("div");
        Object.assign(inputWrap.style, {
            position: "relative",
            marginBottom: "18px",
        });

        const input = document.createElement("input");
        input.type = "password";
        input.inputMode = "numeric";
        input.autocomplete = "new-password";
        Object.assign(input.style, {
            width: "100%",
            boxSizing: "border-box",
            border: "1px solid #cbd5e1",
            borderRadius: "6px",
            padding: "11px 44px 11px 12px",
            fontSize: "18px",
            outline: "none",
        });

        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.setAttribute("aria-label", _t("Show PIN"));
        toggle.title = _t("Show PIN");
        toggle.innerHTML = '<i class="fa fa-eye" aria-hidden="true"></i>';
        Object.assign(toggle.style, {
            position: "absolute",
            top: "50%",
            right: "8px",
            transform: "translateY(-50%)",
            border: "0",
            background: "transparent",
            color: "#64748b",
            cursor: "pointer",
            width: "32px",
            height: "32px",
            fontSize: "16px",
        });

        const actions = document.createElement("div");
        Object.assign(actions.style, {
            display: "flex",
            gap: "10px",
            justifyContent: "flex-end",
        });

        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.textContent = _t("Cancel");
        Object.assign(cancel.style, {
            border: "1px solid #cbd5e1",
            background: "#fff",
            borderRadius: "6px",
            padding: "9px 16px",
            cursor: "pointer",
        });

        const confirm = document.createElement("button");
        confirm.type = "button";
        confirm.textContent = _t("OK");
        Object.assign(confirm.style, {
            border: "0",
            background: "#714B67",
            color: "#fff",
            borderRadius: "6px",
            padding: "9px 20px",
            cursor: "pointer",
            fontWeight: "600",
        });

        inputWrap.append(input, toggle);
        actions.append(cancel, confirm);
        card.append(title, body, inputWrap, actions);
        overlay.appendChild(card);
        document.body.appendChild(overlay);

        function close(value) {
            overlay.remove();
            resolve(value);
        }

        toggle.addEventListener("click", () => {
            const showing = input.type === "text";
            input.type = showing ? "password" : "text";
            toggle.innerHTML = showing
                ? '<i class="fa fa-eye" aria-hidden="true"></i>'
                : '<i class="fa fa-eye-slash" aria-hidden="true"></i>';
            toggle.setAttribute("aria-label", showing ? _t("Show PIN") : _t("Hide PIN"));
            toggle.title = showing ? _t("Show PIN") : _t("Hide PIN");
            input.focus();
        });
        cancel.addEventListener("click", () => close(false));
        confirm.addEventListener("click", () => close(input.value.trim() || false));
        input.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") {
                close(input.value.trim() || false);
            } else if (ev.key === "Escape") {
                close(false);
            }
        });
        overlay.addEventListener("click", (ev) => {
            if (ev.target === overlay) {
                close(false);
            }
        });

        setTimeout(() => input.focus(), 50);
    });
}

async function getMpesaGateTimerMinutes(orm) {
    const now = Date.now();
    if (mpesaSmsTimerConfig !== null && now - mpesaSmsTimerConfigTimestamp < MPESA_TIMER_CONFIG_TTL_MS) {
        return mpesaSmsTimerConfig;
    }
    try {
        const config = await orm.call("pos.config", "sbl_get_backend_gate_lock_minutes", []);
        mpesaSmsTimerConfig = Number(config?.minutes || 0);
    } catch (err) {
        console.warn("[SBL M-Pesa SMS Gate] failed to load backend gate timer:", err);
        mpesaSmsTimerConfig = 0;
    }
    mpesaSmsTimerConfigTimestamp = now;
    return mpesaSmsTimerConfig;
}

function hasMpesaSmsAuthorization() {
    if (!mpesaSmsAuthorized) {
        return false;
    }
    if (mpesaSmsAuthorizedUntil === Infinity || mpesaSmsAuthorizedUntil > Date.now()) {
        return true;
    }
    mpesaSmsAuthorized = false;
    mpesaSmsAuthorizedUntil = 0;
    return false;
}

async function rememberMpesaSmsAuthorization(orm) {
    const minutes = await getMpesaGateTimerMinutes(orm);
    const timeoutMs = minutes * 60 * 1000;
    mpesaSmsAuthorized = true;
    mpesaSmsAuthorizedUntil = timeoutMs > 0 ? Date.now() + timeoutMs : Infinity;
}

async function requestMpesaSmsAuthorization(orm) {
    if (hasMpesaSmsAuthorization()) {
        return true;
    }

    const employeePin = await showMpesaPinDialog(_t("Enter employee PIN to open the M-Pesa SMS app."));
    if (!employeePin) {
        return false;
    }

    const login = await orm.call("hr.employee", "sbl_mpesa_sms_employee_login", [employeePin]);
    if (!login?.success) {
        window.alert(login?.message || _t("Invalid employee PIN."));
        return false;
    }
    if (!login.blocked) {
        await rememberMpesaSmsAuthorization(orm);
        return true;
    }

    const supervisorPin = await showMpesaPinDialog(
        _t(
            "%s is blocked from opening the M-Pesa SMS app. Enter supervisor PIN to authorize.",
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
    await rememberMpesaSmsAuthorization(orm);
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
