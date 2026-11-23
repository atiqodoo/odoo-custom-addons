# Native loyalty reporting

Upgrade `loyalty_points_manager` (18.0.1.2.0) and restart Odoo to load the Python
changes. No earning policies or customer balances are changed by the upgrade.

## Navigation

Users with **Loyalty Audit** access have these Sales menus:

- **Loyalty Points > Reporting > Customer Summary**
- **Loyalty Points > Reporting > Point Movements**
- **Loyalty Points > Reporting > Report Options**

Both reports use native searchable/sortable list, pivot and graph views. Customer
Summary also has a read-only detail form and a Point Movements drill-down.

The models expose normal Odoo search/read/group/export APIs for native Spreadsheet
and Dashboard integrations where those apps and user permissions are installed.
This addon does not install a separate spreadsheet/dashboard template or grant
export rights. Odoo's existing export permission remains required.

## Customer rankings

Customer Summary has one row per contact, loyalty program and card company. It
includes linked active and archived cards; customers without any linked loyalty
card are outside this report. Anonymous cards and other program types are excluded.

Click the relevant column header to sort descending:

- **Current Balance**: live card balances, counted once per card.
- **Recorded Used (All Time)** / **Period Used**: redemption rankings.
- **Balance As Of**: historical closing balance.
- **Peak Recorded Balance** (optional column): historical peak within the stated
  evidence coverage, with its date and evidence quality.

Compare balances within the same loyalty program. Peak balances are not additive
measures: several cards' individual peaks at different times must not be summed.
The report instead calculates the customer's combined balance over the timeline.

**Report Options** selects the point-movement period, balance-as-of date and
inactivity threshold. Dates use the user's timezone and include the full selected
local day. Reopening options from a report retains its selected settings.

**Dormant Purchasers** means a prior qualifying purchase exists and the days since
that purchase reach the chosen threshold. Zero disables dormancy. **Dormant with
Points**, **Never Purchased** and **Never Redeemed** are separate filters. Purchase
activity uses currently paid/done/invoiced positive POS orders, excluding returned
COD orders, and confirmed positive Sales orders. It is scoped to the contact and
company, rather than to whether each purchase earned points in this program.

## Movements and historical confidence

Point Movements uses captured audit events and only the uncovered amounts of
legacy history. It does not count an event and its history total twice. Standalone
cancellation events remain visible when standard Sales history is deleted;
cancellation net movements are shown separately from earned/redemption amounts.

Native grouping includes customer, program, POS order, Sales order, order POS
session, COD collection session, company, source and date. Collection sessions
are frozen on new COD audit events. Unknown historical collection sessions are
left blank instead of being inferred from the order's latest collection.

Historical balances have explicit confidence labels:

- **Current live balance**: the selected date is today.
- **Captured interval**: anchored audit movements reconcile to the live balance
  over the stated interval.
- **Reconstructed ledger**: legacy record creation dates are used; those dates
  may differ from when points actually moved, especially for edited Sales history.
- **Insufficient history**: the ledger cannot reconcile, or the requested date
  predates available balance coverage.

Use **Known Historical Balance** / **Known Recorded Peak** before ranking historical
values. An unavailable value is not evidence of zero points. Closing balances
and recorded peaks are qualified by their evidence interval, not presented as a
guaranteed all-time history. Recorded totals describe available movements rather
than proving that missing historic transactions never existed.

Reports enforce allowed companies inside the SQL queries and through record
rules. Shared cards retain their explicitly shared live balance, while movement
totals only include allowed companies. A resulting historical reconciliation gap
is labelled insufficient history. Reports are read-only; filtering and exporting
do not change cards, history or earning policy.

The existing History report no longer sums repeated current-card balances or
offers that field as a pivot/graph measure. Current balance analysis belongs in
Customer Summary.

## Technical validation

SQL is limited to reporting aggregation and window calculations. Dynamic values
are parameterized with Odoo's SQL wrapper. The two report models share one movement
query, declare ORM flush dependencies, and preserve report context in field caches.
The summary batches per-card aggregation rather than issuing one ORM query per
customer. Report query generation logs use `[LPM][REPORT]`; report option boundaries
use `[LPM][REPORT_OPTIONS]`. Full customer data is not included in these logs.

Run `--test-enable --test-tags=/loyalty_points_manager --stop-after-init` on an
isolated database. Reporting tests cover duplicate prevention, current/as-of
balances, periods, historical coverage, combined peaks, same-second movements,
timezone cutoffs, dormancy, sessions, cancellation retention, export/grouping,
read-only permissions, shared cards and company isolation.
