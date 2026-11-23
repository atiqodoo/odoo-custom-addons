# Native Record Alarms for Odoo 18

Adds native Odoo alarm records, date/time scheduling, a sound activation button in
the webclient top bar, Stop/Snooze, authorised LAN PCs, and company-specific Settings.
No native Odoo source files are modified.

## Install and use

1. Install **Native Record Alarms** from Apps. Install the optional **Native Alarms -
   Project and To-Do** and **Native Alarms - Sales Quotations** connectors for those apps.
   Connectors also auto-install when their dependencies are installed.
2. Set each person's timezone in their Odoo preferences. Alarm input/display follows
   the current Odoo user's timezone; storage and companion exchange use UTC.
3. Open a saved quotation, task, To-Do, project, or activity. Choose **Action > Set Alarm**.
   Select exactly one record when working from a list. The Activity scheduling dialog
   also includes **Ring an alarm** and its date/time/delivery settings.
4. Enter the alarm datetime. Choose **My Odoo browser**, **Registered PC**, or **Browser
   and PC**. Set snooze minutes, ring seconds, optional repeat minutes, and whether
   completion should suppress delivery. Save the alarm.
5. For browser sound, click **Alarm sound** in the top bar or **Enable / test sound**
   in an alarm popup. Enable audio again after refreshing/reopening the page. Keep Odoo
   open. For PC sound, register and install the companion described in
   `C:\odoo18\alarm_companion\README.md`.

The Alarms app lists records and offers Stop, Snooze, Cancel Alarm, and Open Source.
Open Source is also available in browser and Windows alarm popups. Activity alarms
resolve to the activity's business document (To-Do, quotation, etc.). The link checks
the alarm and source permissions as the logged-in browser user; opening it does not
stop the alarm. Deleted, inaccessible or moved-company sources cannot be opened.
The companion uses an authenticated Odoo redirect, so no source IDs or names need
to be added to the cached schedule. The existing `action_open_record` method remains
available for compatibility. Connectors can implement `_native_alarm_source_record()`
on a reminder model to resolve its business source.
Ordinary users manage their own alarms; **Alarm Administrator** can schedule for
colleagues, configure PCs, and enable additional persistent record types. Native
permissions on the linked record are always required. Creating an Activity still
requires Odoo's normal Activity/source-document permissions.

## Company alarm defaults

Open **Alarms > Settings** (Settings administrators only), or **Settings > Alarms**.
Configure default delivery, registered PC, ring duration, snooze, repeat interval,
silence-on-completion and company sound. These options prefill new record alarms and
the native Schedule Activity dialog; individual alarms can override them. Changing
defaults never rewrites existing alarms. The date/time remains user-entered and
**Ring an alarm** remains opt-in.

PC delivery requires an active default PC in the same company. A PC is only prefilled
when the recipient is authorised to ring it. Other recipients must choose an authorised
PC or browser delivery; settings cannot bypass device permissions. Zero ring seconds
means ring until stopped, and zero repeat minutes disables repetition. Repeat is
scheduled after Stop. The activity dialog now offers ring, repeat, snooze and completion
overrides alongside its delivery/device fields.

## Songs: default or per alarm

1. An Alarm Administrator opens **Alarms > Sound Library**, uploads a song, names it,
   and saves. Use the native audio preview controls to verify playback.
2. **Settings > Alarms > Default sound for this company** selects the default for
   every alarm without an override. Leave it empty for the browser's built-in tone.
3. On an individual alarm choose **Sound override** to use another approved song.
   Clear the override to follow the company default again.

Supported uploads: MP3, WAV, OGG/OGA, FLAC, M4A, AAC, WMA. Playback depends on the browser
or Windows decoder; MP3/WAV are recommended. WMA in particular is not generally supported
by Chrome. Unsupported browser files fall back to a built-in tone and show a warning.
Files are validated by extension/container signature and the editable upload size limit;
this is not full decoding verification. Preview the actual uploaded song before relying on it.

Sounds have a company scope, or can be shared across companies by an administrator.
Ordinary internal users can select/read approved sounds in their allowed scope; they cannot
upload, modify, or delete library entries. Preview/playback uses authenticated Odoo content
routes, without public access tokens. No song is bundled or uploaded by the addon itself.

The updated companion downloads the selected effective sound through the authenticated
Odoo API, verifies its SHA-256 checksum, and caches the complete file for offline playback.
Existing companion deployments need their installed companion.py replaced and both service
and desktop player restarted. Older players continue using their own local fallback sound.

## Configuration

Settings > Alarms stores refresh seconds, offline cache horizon, missed tolerance,
default snooze, and default ring duration per company. These are editable defaults,
not fixed business thresholds. Zero ring seconds means continuous sound until stopped
(while the player remains available). Zero repeat minutes disables recurrence.
Zero missed-tolerance minutes disables the age cutoff for starting missed alarms.
Recurrence is an elapsed-minute interval after Stop; it is not a daily/weekly local-time
calendar scheduler. Snooze does not complete the source record.

Alarms > Registered PCs stores the device name, company, dedicated companion account,
authorised recipients, and last successful connection. One alarm targets one PC; create
separate alarms if multiple PCs should ring. Browser-and-PC intentionally targets both;
responses propagate on the next synchronisation.

Alarms > Enabled Record Types creates native **Set Alarm** contextual actions for
additional business models. Generic integrations respect access rights, company, record
existence, and the `active` field. Specific completion rules use the source model hook
`_native_alarm_is_active()`, implemented in optional connectors through Odoo inheritance.
Sales draft/sent quotation alarms stop delivering after confirmation/cancellation;
Project/To-Do alarms stop delivering when closed; Activity alarms stop delivering after
completion or deletion. The source record's status is not modified by an alarm response.

## Delivery and privacy

The companion uses Odoo's native XML-RPC API and API-key authentication. The service
account requires **Alarm Companion Account** and its device company. It does not need
Sales/Project access to fetch the minimal schedule; a narrowly scoped server boundary
checks device identity and source access as each recipient before returning the alarm
title/time/options. A device can never acknowledge an alarm assigned only to another PC.

The browser is a delivery adapter, not the scheduling authority. It loops the selected
approved song, or uses a built-in two-tone ringtone when no song is configured. Windows
uses the cached Odoo song, falling back to its locally selected audio file when no Odoo
song is configured. Configure volume and speaker routing in Windows.

Snapshots retain old scheduled alarms so an existing continuous ringtone is not cut off
by missed tolerance. Players apply missed tolerance before beginning a new ringtone.
Old alarms remain available for cancellation/review. Delivery, cancellation, permission,
and source-state changes reach connected players on the next configurable refresh.
Offline players cannot know about remote cancellations or permission changes until
reconnection; protect the cache with the supplied Windows account ACLs.

Scheduling and response operations log safe `[NATIVE_ALARM][OPERATION][START/END/ERROR]`
boundaries. Enable `odoo.addons.native_alarm:DEBUG` to inspect them. Titles, notes,
credentials, and API keys are not included in these boundary logs.

## Validation commands

From `C:\odoo18`:

```powershell
.\python\python.exe tmp\run_native_alarm_tests.py
.\python\python.exe -m unittest discover -s alarm_companion\tests -v
node --experimental-vm-modules --test custom_addon/native_alarm/tests/browser_service.test.mjs
```

The first command creates a new isolated PostgreSQL database using the development
connection configuration. It does not install into or update the production database.
`--reuse` reuses only the isolated database recorded by this test runner.
