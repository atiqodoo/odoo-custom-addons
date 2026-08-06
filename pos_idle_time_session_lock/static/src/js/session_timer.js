/** @odoo-module **/
import { Chrome } from "@point_of_sale/app/pos_app";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { onWillUnmount, reactive, useEffect, useExternalListener, useRef, useState, onWillStart } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";

var updatedTime;
var idleTimer;
var serverAuditAvailable = true;
var fallbackAuditAvailable = true;

function fallbackAuditIdleLock(message, details = {}, pos = null) {
    if (!fallbackAuditAvailable) {
        return;
    }
    rpc("/pos_direct_thermal_printer/log", {
        level: "info",
        message: "POS_IDLE_LOCK " + message,
        data: details,
        config_id: pos?.config?.id || details?.config_id || null,
        order_uid: null,
    }).catch((error) => {
        fallbackAuditAvailable = false;
        console.warn("[pos_idle_time_session_lock]", "fallback_audit_failed", {
            message,
            error,
        });
    });
}

function auditIdleLock(message, details = {}, pos = null) {
    console.info("[pos_idle_time_session_lock]", message, details);
    const sessionId = pos?.config?.current_session_id?.id || pos?.session?.id;
    if (serverAuditAvailable && pos?.data?.call && sessionId) {
        pos.data.call("pos.session", "pos_idle_lock_audit", [sessionId, message, details]).catch((error) => {
            serverAuditAvailable = false;
            console.warn("[pos_idle_time_session_lock]", "audit_rpc_failed", {
                message,
                error,
            });
            fallbackAuditIdleLock(message, details, pos);
        });
    } else {
        fallbackAuditIdleLock(message, details, pos);
    }
}

patch(Navbar.prototype, {
    setup() {
        super.setup(...arguments);
        useExternalListener(window, "click", this.onWindowClick, true);
        useExternalListener(window, "keypress", this.onWindowKeypress, true);
        this.rootRef = useRef("root");
        this.timerState = useState({ time: null });
        this.count_down_time = this.pos.config.idle_time_limit || 0;
        onWillStart(() => this.set_timer());
        onWillUnmount(() => {
            if (idleTimer) {
                clearInterval(idleTimer);
                idleTimer = null;
            }
        });
    },
    set_timer() {
        var self = this;
        var count_down_time = self.count_down_time;
        var pos_lock = self.pos.config.pos_lock;
        if (pos_lock) {
            if (idleTimer) {
                clearInterval(idleTimer);
                idleTimer = null;
            }
            var now = new Date().getTime();
            var date = new Date(now);
            date.setMinutes(date.getMinutes() + count_down_time);
            updatedTime = date.getTime();
            auditIdleLock("timer_started", {
                config_id: self.pos.config.id,
                idle_time_limit: count_down_time,
                expires_at: new Date(updatedTime).toISOString(),
            }, self.pos);
            idleTimer = setInterval(function() {
                var now = new Date().getTime();
                var distance = updatedTime - now;
                var days = Math.floor(distance / (1000 * 60 * 60 * 24));
                var hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                var minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
                var seconds = Math.floor((distance % (1000 * 60)) / 1000);
                self.timerState.time = hours + " h " + minutes + " m " + seconds + " s ";
                if (distance <= 0) {
                    clearInterval(idleTimer);
                    idleTimer = null;
                    var cashier = self.pos.get_cashier && self.pos.get_cashier();
                    auditIdleLock("idle_timeout_locking_session", {
                        config_id: self.pos.config.id,
                        cashier_id: cashier && cashier.id,
                        cashier_name: cashier && cashier.name,
                        module_pos_hr: self.pos.config.module_pos_hr,
                    }, self.pos);
                    if (self.pos.config.module_pos_hr) {
                        if (self.pos.reset_cashier) {
                            self.pos.reset_cashier();
                        }
                        self.pos.login = true;
                        auditIdleLock("cashier_cleared_for_relogin", {
                            config_id: self.pos.config.id,
                            previous_cashier_id: cashier && cashier.id,
                            previous_cashier_name: cashier && cashier.name,
                        }, self.pos);
                        self.pos.showScreen("LoginScreen");
                    } else {
                        self.pos.showScreen("LoginScreen");
                    }
                }
            }, 1000);
        }
    },
    onWindowClick() {
        this.resetTimer();
    },
    onWindowKeypress() {
        this.resetTimer();
    },
    resetTimer() {
        if (!this.pos.config.pos_lock) {
            return;
        }
        if (!idleTimer) {
            this.set_timer();
            return;
        }
        var now = new Date().getTime();
        var date = new Date(now);
        date.setMinutes(date.getMinutes() + this.count_down_time);
        updatedTime = date.getTime();
        console.debug("[pos_idle_time_session_lock]", "timer_reset", {
            config_id: this.pos.config.id,
            expires_at: new Date(updatedTime).toISOString(),
        });
    },
});
