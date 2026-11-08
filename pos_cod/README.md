# COD collection promises

Upgrade `pos_cod`, restart Odoo, and reload open POS terminals after deploying.
In Point of Sale Settings, select the terminal and enable **COD Collection
Promises and Reminders**. Cash on Delivery must also be enabled on that POS.

Configure calendar days after dispatch (0 = same day, 1 = next day, etc.), the
default collection time, collection timezone, repeat interval in minutes, and
refresh interval in seconds. The default time setting uses Odoo's standard
time widget. The dispatch wizard uses a DD/MM/YYYY calendar and explicit
12-hour hour/minute inputs with AM/PM. Both date and time remain editable.

The backend checks that the selected promise is later than dispatch time.
A passed same-day cutoff needs cashier correction; the date never silently
rolls forward. Dates follow the configured timezone, not the session opening
or closing date. Saved promises are UTC datetimes and are preserved on retries
and when settings change. Old orders without a promise are not backfilled.

While POS is running, reminders include accessible, dispatched, collectible
COD orders in its company across terminals and sessions. Existing collection
balance methods determine what remains due, including payment, return,
discount, deposit and cheque adjustments provided by installed extensions.
The dialog blocks underlying POS input and barcode scans until X is clicked.
Escape does not close it. The repeat interval begins after dismissal. One
popup is shown at a time; other active dialogs defer it. Closing a reminder
does not collect payment or alter the promise.

Refreshes run periodically, at the nearest known deadline, after local COD
dispatch/collection, and on reconnect or window focus. Failed checks retain
the last known status and flag it as stale. A suspended browser or closed POS
cannot display a reminder until it resumes. Reload POS after settings changes.

Tests:

```powershell
node --test custom_addon/pos_cod/tests/promise_client.test.mjs
python server/odoo-bin -c <test-config> -d <isolated-test-database> -u pos_cod --test-enable --test-tags /pos_cod --stop-after-init --no-http --max-cron-threads=0
```

Backend debug headers: `[COD][PROMISE_SETTINGS]`,
`[COD][PROMISE_SETTINGS_CREATE]`, `[COD][PROMISE_DEFAULTS]`,
`[COD][PROMISE_VALIDATE]`, and `[COD][OVERDUE_REMINDERS]`.
