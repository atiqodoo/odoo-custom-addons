/** @odoo-module **/
import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export const alarmService = {
    dependencies: ["orm", "notification", "action"],
    start(env, { orm, notification, action }) {
        let audio;
        let schedule = [];
        let offset = 0;
        let pollSeconds;
        let missedMinutes = 0;
        let busy = false;
        const displayed = new Map();
        // Ephemeral tab identity, not an authentication token; also works on LAN HTTP.
        const owner = `${Date.now()}:${Math.random()}`;
        const leaseKey = `native_alarm_audio_leader:${session.db}:${session.uid}`;
        let leader = false;

        function stopTone(item) {
            clearInterval(item.toneTimer);
            clearTimeout(item.stopTimer);
            item.toneTimer = null;
            if (item.media) {
                const media = item.media;
                item.media = null;
                media.pause();
                media.src = "";
            }
        }
        function tone() {
            if (!audio || audio.state !== "running") {
                return;
            }
            // Synthesised two-tone ringtone; no remote audio asset or permission is needed.
            for (const [index, frequency] of [660, 880].entries()) {
                const oscillator = audio.createOscillator();
                const gain = audio.createGain();
                gain.gain.value = 0.15;
                oscillator.frequency.value = frequency;
                oscillator.connect(gain).connect(audio.destination);
                oscillator.start(audio.currentTime + index * 0.18);
                oscillator.stop(audio.currentTime + index * 0.18 + 0.16);
            }
        }
        function startTone(item) {
            if (item.toneTimer || item.media || !audio || audio.state !== "running") {
                return;
            }
            const builtIn = () => { tone(); item.toneTimer = setInterval(tone, 1500); };
            if (item.alarm.sound) {
                const media = new Audio(item.alarm.sound.url);
                media.loop = true;
                item.media = media;
                const failed = () => {
                    if (item.media !== media) { return; }
                    item.media = null;
                    media.pause();
                    media.src = "";
                    notification.add(_t("The selected alarm file could not play. Using the built-in tone. Preview the file in Sound Library or choose MP3/WAV."), { type: "warning" });
                    builtIn();
                };
                media.onerror = failed;
                try { Promise.resolve(media.play()).catch(failed); } catch { failed(); }
            } else {
                builtIn();
            }
            if (item.alarm.ring_seconds) {
                item.stopTimer = setTimeout(() => stopTone(item), item.alarm.ring_seconds * 1000);
            }
        }
        async function enableSound() {
            try {
                audio ||= new AudioContext();
                await audio.resume();
                if (audio.state !== "running") {
                    throw new Error("Alarm audio is not running");
                }
                localStorage.setItem(leaseKey, JSON.stringify({ owner, until: Date.now() + 4000 }));
                tone();
                for (const item of displayed.values()) {
                    startTone(item);
                }
            } catch {
                notification.add(_t("Your browser blocked alarm sound. Allow sound for this site and try again."), { type: "warning" });
            }
        }
        async function respond(item, operation) {
            try {
                await orm.call("native.alarm", "browser_respond", [[item.alarm.id], operation, item.alarm.revision]);
                stopTone(item);
                item.remove();
                displayed.delete(item.key);
                await refresh();
            } catch {
                notification.add(_t("The alarm response could not be saved. Check your connection and retry."), { type: "warning" });
            }
        }
        async function openSource(alarm) {
            try {
                const source = await orm.call('native.alarm', 'action_open_record', [[alarm.id]]);
                await action.doAction(source);
            } catch {
                notification.add(_t('The source record is unavailable or you no longer have access to it.'), { type: 'warning' });
            }
        }
        function tick() {
            // A renewable same-origin lease avoids simultaneous ringing in multiple tabs.
            // localStorage failures disable audio leadership rather than breaking the web client.
            try {
                const lease = JSON.parse(localStorage.getItem(leaseKey) || "null");
                leader = !lease || lease.owner === owner || lease.until < Date.now();
                if (leader) {
                    localStorage.setItem(leaseKey, JSON.stringify({ owner, until: Date.now() + 4000 }));
                }
            } catch { leader = false; }
            if (!leader) {
                for (const item of displayed.values()) { stopTone(item); item.remove(); }
                displayed.clear();
                return;
            }
            const now = Date.now() + offset;
            for (const alarm of schedule) {
                const key = `${alarm.id}:${alarm.revision}:${alarm.sound?.checksum || "tone"}`;
                const due = Date.parse(`${alarm.alarm_at.replace(" ", "T")}Z`);
                if (due > now || (missedMinutes > 0 && now - due > missedMinutes * 60000) || displayed.has(key)) {
                    continue;
                }
                const item = { key, alarm };
                item.remove = notification.add(alarm.name, {
                    title: _t("Alarm"), type: "warning", sticky: true,
                    onClose: () => stopTone(item),
                    buttons: [
                        { name: _t("Stop"), primary: true, onClick: () => respond(item, "stop") },
                        { name: _t("Snooze"), onClick: () => respond(item, "snooze") },
                        { name: _t("Open Alarm"), onClick: () => action.doAction({
                            type: "ir.actions.act_window", res_model: "native.alarm",
                            res_id: alarm.id, views: [[false, "form"]],
                        }) },
                        { name: _t('Open Source'), onClick: () => openSource(alarm) },
                        { name: _t("Enable / test sound"), onClick: enableSound },
                    ],
                });
                displayed.set(key, item);
                startTone(item);
            }
        }
        async function refresh() {
            if (busy) { return; }
            busy = true;
            try {
                const result = await orm.call("native.alarm", "browser_schedule", []);
                offset = Date.parse(`${result.server_time.replace(" ", "T")}Z`) - Date.now();
                pollSeconds = result.poll_seconds;
                missedMinutes = result.missed_minutes;
                schedule = result.alarms;
                const keys = new Set(schedule.map(a => `${a.id}:${a.revision}:${a.sound?.checksum || "tone"}`));
                for (const [key, item] of displayed) {
                    if (!keys.has(key)) { stopTone(item); item.remove(); displayed.delete(key); }
                }
                tick();
            } catch (error) {
                console.debug("[NATIVE_ALARM][BROWSER_SYNC][ERROR]", error.name);
            } finally {
                busy = false;
            }
        }
        async function poll() {
            await refresh();
            // Before settings can be fetched, retry at a technical connection backoff.
            setTimeout(poll, (pollSeconds || 30) * 1000);
        }
        setInterval(tick, 1000);
        poll();
        return { enableSound };
    },
};
registry.category("services").add("native_alarm", alarmService);

class AlarmSound extends Component {
    static template = xml`<div class="o_native_alarm_sound d-flex align-items-center"><button type="button" class="btn btn-link" title="Enable / test alarm sound" aria-label="Enable alarm sound" t-on-click="enable"><i class="fa fa-bell"/><span class="d-none d-md-inline ms-1">Alarm sound</span></button></div>`;
    static props = {};
    setup() { this.alarm = useService("native_alarm"); }
    enable() { this.alarm.enableSound(); }
}
registry.category("systray").add("native_alarm.sound", { Component: AlarmSound }, { sequence: 30 });

class AlarmAudioPreview extends Component {
    static props = { ...standardFieldProps };
    static template = xml`<div><audio t-if="props.record.data[props.name]" controls="controls" preload="none" t-att-src="props.record.data[props.name]"/><span t-else="">Save the sound to preview it.</span></div>`;
}
registry.category("fields").add("native_alarm_audio", {
    component: AlarmAudioPreview, supportedTypes: ["char"],
});
