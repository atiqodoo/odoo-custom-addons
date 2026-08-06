/** @odoo-module **/

/**
 * App Gate Service — intercepts Odoo home-menu app clicks.
 *
 * Flow:
 *   1. sbl.app.gate.config defines which apps are globally gated (always need PIN).
 *   2. When a gated app is clicked, a PIN dialog appears.
 *   3. The employee enters their PIN — the server identifies WHO they are.
 *   4. If their sbl_blocked_app_ids includes this app → "Employee X is not
 *      authorized to access Y" (dialog stays open for another attempt).
 *   5. If not blocked → access granted, navigation proceeds.
 *
 * This means any employee at the keyboard must prove their identity via PIN,
 * regardless of which Odoo user is currently logged in.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

// ── constants ────────────────────────────────────────────────────────────────

/** Apps already handled by a dedicated gate — skip to avoid double prompts. */
const SBL_SKIP_XMLIDS = new Set(["mpesa_c2b_sms.menu_mpesa_root"]);

/** Client-side cache TTL: 5 minutes. */
const SBL_CACHE_TTL_MS = 5 * 60 * 1000;

// ── module-level cache ───────────────────────────────────────────────────────

let _gatedXmlids = null;
let _cacheTimestamp = 0;

// ── server helpers ───────────────────────────────────────────────────────────

/**
 * Fetch ALL globally-gated app XML IDs from the server (cached).
 * Every app in sbl.app.gate.config appears here — gating is independent of
 * which Odoo user is logged in.
 */
async function sblGetGatedXmlids(orm) {
    const now = Date.now();
    if (_gatedXmlids !== null && now - _cacheTimestamp < SBL_CACHE_TTL_MS) {
        return _gatedXmlids;
    }
    try {
        const config = await orm.call("hr.employee", "sbl_get_app_gate_config", []);
        _gatedXmlids = new Set(config.blocked_apps || []);
        console.log("[AppGate] gated apps loaded:", [..._gatedXmlids]);
    } catch (err) {
        console.error("[AppGate] failed to load gated apps:", err);
        _gatedXmlids = new Set();
    }
    _cacheTimestamp = now;
    return _gatedXmlids;
}

function sblBustCache() {
    _gatedXmlids = null;
    _cacheTimestamp = 0;
}

/**
 * Given a clicked menu item, find the matching gated-app entry.
 * Returns { xmlid, name } or null.
 */
function sblFindGatedApp(menu, menuService, gatedXmlids) {
    if (!menu || !gatedXmlids || gatedXmlids.size === 0) {
        return null;
    }
    for (const xmlid of gatedXmlids) {
        if (SBL_SKIP_XMLIDS.has(xmlid)) {
            continue;
        }
        const app = menuService.getApps().find((a) => a.xmlid === xmlid);
        if (app && (menu.id === app.id || menu.appID === app.id)) {
            return { xmlid, name: app.name };
        }
    }
    return null;
}

// ── PIN dialog ────────────────────────────────────────────────────────────────

/**
 * Build and show a styled PIN dialog overlay.
 *
 * The dialog stays open on wrong PIN / blocked employee so the user can retry
 * or cancel. resolve(true) is called only on a successful server response.
 */
function sblShowPinDialog(app, orm, resolve) {
    // ── overlay ──
    const overlay = document.createElement("div");
    Object.assign(overlay.style, {
        position: "fixed",
        top: "0",
        left: "0",
        width: "100%",
        height: "100%",
        background: "rgba(0,0,0,0.55)",
        zIndex: "10000",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
    });

    // ── card ──
    const card = document.createElement("div");
    Object.assign(card.style, {
        background: "#fff",
        borderRadius: "10px",
        padding: "28px 32px",
        width: "340px",
        boxShadow: "0 8px 32px rgba(0,0,0,0.28)",
        fontFamily: "inherit",
    });

    card.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
            <span style="font-size:24px;line-height:1;">&#128274;</span>
            <h5 style="margin:0;font-size:16px;font-weight:700;color:#1f1f1f;">App Gate</h5>
        </div>
        <p style="margin:0 0 18px;color:#555;font-size:14px;line-height:1.5;">
            Enter your <strong>Employee PIN</strong> to open<br/>
            <strong style="color:#714B67;font-size:15px;">${app.name}</strong>
        </p>

        <input id="sbl_gate_pin"
               type="password"
               inputmode="numeric"
               maxlength="8"
               autocomplete="new-password"
               placeholder=""
               readonly
               style="width:100%;padding:12px;border:2px solid #ddd;border-radius:6px;
                      font-size:22px;text-align:center;letter-spacing:8px;
                      box-sizing:border-box;outline:none;transition:border-color .15s;"/>

        <div id="sbl_gate_error"
             style="min-height:40px;margin-top:10px;font-size:13px;color:#dc3545;
                    text-align:center;line-height:1.4;font-weight:500;">
        </div>

        <div style="display:flex;gap:10px;margin-top:14px;">
            <button id="sbl_gate_cancel"
                    style="flex:1;padding:10px;border:1px solid #ccc;border-radius:6px;
                           background:#fff;cursor:pointer;font-size:14px;color:#333;">
                Cancel
            </button>
            <button id="sbl_gate_confirm"
                    style="flex:2;padding:10px;border:none;border-radius:6px;
                           background:#714B67;color:#fff;cursor:pointer;
                           font-size:14px;font-weight:600;transition:opacity .15s;">
                Confirm
            </button>
        </div>
    `;

    overlay.appendChild(card);
    document.body.appendChild(overlay);

    const pinInput  = card.querySelector("#sbl_gate_pin");
    const errorDiv  = card.querySelector("#sbl_gate_error");
    const cancelBtn = card.querySelector("#sbl_gate_cancel");
    const confirmBtn = card.querySelector("#sbl_gate_confirm");

    // Remove readonly and clear any autofill on first interaction
    pinInput.addEventListener("focus", () => {
        pinInput.removeAttribute("readonly");
        pinInput.value = "";
        pinInput.style.borderColor = "#714B67";
    });
    pinInput.addEventListener("blur", () => { pinInput.style.borderColor = "#ddd"; });

    // Trigger focus after a tick so the browser autofill fires first, then we clear it
    setTimeout(() => { pinInput.focus(); }, 50);

    function close(success) {
        document.body.removeChild(overlay);
        resolve(success);
    }

    function setLoading(loading) {
        confirmBtn.disabled = loading;
        confirmBtn.style.opacity = loading ? "0.65" : "1";
        confirmBtn.textContent = loading ? "Verifying…" : "Confirm";
    }

    async function tryConfirm() {
        const pin = pinInput.value.trim();
        if (!pin) {
            errorDiv.textContent = _t("Please enter your PIN.");
            pinInput.focus();
            return;
        }

        setLoading(true);
        errorDiv.textContent = "";

        let result;
        try {
            result = await orm.call("hr.employee", "sbl_app_gate_login", [
                pin,
                app.xmlid,
                app.name,
            ]);
        } catch {
            errorDiv.textContent = _t("Connection error — please try again.");
            setLoading(false);
            pinInput.select();
            return;
        }

        if (result?.success) {
            close(true);
            return;
        }

        // Show specific message: "Employee X is not authorized" or "Invalid PIN"
        errorDiv.textContent = result?.message || _t("Access denied.");

        // If employee was specifically blocked (not just wrong PIN), highlight differently
        if (result?.blocked) {
            errorDiv.style.color = "#c0392b";
            errorDiv.style.fontWeight = "700";
        } else {
            errorDiv.style.color = "#dc3545";
            errorDiv.style.fontWeight = "500";
        }

        pinInput.value = "";
        pinInput.focus();
        setLoading(false);
        sblBustCache();
    }

    cancelBtn.addEventListener("click", () => close(false));
    confirmBtn.addEventListener("click", tryConfirm);
    pinInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") tryConfirm();
        if (e.key === "Escape") close(false);
    });
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) close(false);
    });
}

/**
 * Show the PIN dialog for the given app and return a promise that resolves
 * to true (allowed) or false (cancelled or denied).
 */
async function sblRequestPin(orm, app) {
    return new Promise((resolve) => sblShowPinDialog(app, orm, resolve));
}

// ── service patch ─────────────────────────────────────────────────────────────

const serviceRegistry = registry.category("services");

// Capture the currently-registered menu service definition (may already be
// the M-Pesa-patched version if mpesa_sms_app_gate.js loaded first).
const _baseMenuDefinition = serviceRegistry.get("menu");

serviceRegistry.add(
    "menu",
    {
        ..._baseMenuDefinition,
        dependencies: Array.from(
            new Set([...(_baseMenuDefinition.dependencies || []), "orm"])
        ),

        async start(env, dependencies) {
            const service = await _baseMenuDefinition.start(env, dependencies);
            const _originalSelectMenu = service.selectMenu.bind(service);

            service.selectMenu = async function sblSelectMenu(menu) {
                const resolved =
                    typeof menu === "number" ? service.getMenu(menu) : menu;

                console.log("[AppGate] selectMenu called:", resolved?.xmlid, resolved?.name);

                if (resolved) {
                    const gatedXmlids = await sblGetGatedXmlids(dependencies.orm);
                    const gatedApp = sblFindGatedApp(resolved, service, gatedXmlids);
                    console.log("[AppGate] gatedApp found:", gatedApp);
                    if (gatedApp) {
                        const allowed = await sblRequestPin(dependencies.orm, gatedApp);
                        if (!allowed) {
                            return; // Block navigation.
                        }
                    }
                }

                return _originalSelectMenu(menu);
            };

            return service;
        },
    },
    { force: true }
);
