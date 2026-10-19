# Review the app in Codespaces

This setup gives you a separate PostgreSQL database containing synthetic sample
data. It uses Python 3.11 and requires no Heroku credentials or database backup.
Creating a Codespace does not merge or deploy the review branch.

## Open a new Codespace

1. Open the repository's `owner-overhead-settings` branch on GitHub.
2. Choose **Code → Codespaces → Create codespace**. If using **New with options**,
   select the **Haulage review** dev container.
3. Wait for the development container setup to finish. It installs the packages,
   creates the review database and adds sample records automatically. The setup
   output ends with **Review setup ready**.
4. In the terminal, from the repository directory, run:

   ```bash
   python3 run.py
   ```

5. Open the **Ports** tab, find **8080**, and select **Open in Browser**. Keep the
   port's Codespaces visibility **Private**, which is the default. Its port
   protocol is **HTTP**, as configured by the dev container; the browser's
   `app.github.dev` address still uses **HTTPS**.

The app stays running in that terminal. Press **Ctrl+C** to stop it; run the same
command to start it again. Normal restarts and container rebuilds preserve the
review database and your edits. Deleting the Codespace deletes this preview.

## What to review

The setup output gives dated links relative to the day the sample data was
created. Open those paths on your preview's address:

| Example | What to look for |
| --- | --- |
| Complete example week | Clear financial summary, driver/truck views and an explicit review status. The seeded figures are £9,625 earnings, £3,128 employer wage cost, £1,490 fuel, £1,400 overheads and £3,607 estimated result. |
| Checks to practise | A compact Driver / truck, Check and Review table has one **Review** link per issue. Open a missing day, payslip, fuel receipt or unusual job amount to inspect the week and enter a correction on the same page. Missing fuel also offers **The fuel tick was a mistake**. |
| Duplicate payslip example | Compare both entries, edit an existing payslip's amounts, explicitly confirm a duplicate removal, or verify genuinely separate payslips with an explanation. |
| Previous month | Whole payroll weeks, monthly totals and review status. |
| Current partial week | Only entries due so far; later dates remain outside the figures. If you create the preview at a weekend, there may be no Working days yet. |
| Truck and overhead settings | Four sample trucks, with a dated allowance change from £350 to £400 per truck per week. These are demo amounts. |

Start at `/owner-analysis` or use the complete-week link from setup. Missing
financial information deliberately leaves the example issue week's profit
pending. Holiday/Absent records, a one-day truck exchange and the dated overhead
change provide other examples to inspect. Your edits affect only this preview.

Driver and truck cards have read-only **View week** / **View details** popups.
Drivers show jobs and destinations; trucks show daily readings and fuel receipts.
Ordinary weekends have no day entry and are not counted as absences. An
occasional Saturday job illustrates actual weekend work.

On a check's review page, try an invalid correction or an incomplete
verification explanation. The selected check, weekly evidence and entered text
stay visible so you can correct the submission. Saves return to the original
weekly/monthly checks period. Missing weekdays still require an actual
Working/Holiday/Absent record. Where allowed, try **Dismiss with explanation** for a known false alarm. On missing
fuel, **Awaiting fuel invoice** saves a reason but keeps the check outstanding,
profit pending and final review blocked. Saved decisions appear in history and
reopen if their source records change.

Fuel typo checks compare cost per purchased litre, with broad £0.50–£3.00 limits.
Matching truck/date/provider/litres/cost raises one possible-duplicate comparison;
remove a receipt only after checking the actual invoice lines. Payroll compares
take-home pay with full employer cost on the same payslip; variable bonuses are
allowed. Mileage and truck-assignment hints sit under collapsed **Other checks**
and do not affect the main count or final weekly review.

Days, fuel and payroll use the following Friday–Monday review window. Outstanding
records show **Awaiting records** through Monday, then **Needs review**. A ready
week can be signed off earlier. Monthly checks use completed payroll weeks only.

On the complete example week, click **Mark as checked**. The button changes to
**Undo**; click it to reopen the weekly review, then check the week again. No
tickboxes or optional sign-off note are needed. Open **History** to see both the
original review and its undo record. Source entries and per-check decisions are
preserved. A stale page cannot undo a newer sign-off. Separate business-week
notes remain available under a collapsed link.

When updating an existing preview, stop the server with **Ctrl+C**, then run:

```bash
git pull --ff-only
python3 tools/setup_review.py
python3 run.py
```

This update needs that setup command even on an existing preview: it safely
widens the recognised owner-review decision constraint to allow the new saved
decisions. It retains existing rows and explanations. If the existing constraint
is missing or unrecognised, setup stops without changing it. It does not stamp
or replay the migration chain.

The setup keeps existing records and edits. It can remove the original demo's
empty weekend Absent entries only when it recognises the synthetic fixture and
the individual rows are untouched. Changed or newly entered statuses and linked
records are preserved; a skipped cleanup is explained in the terminal.

## If setup needs retrying

### Preview connection fails

Keep `python3 run.py` running and open the preview from **Ports → 8080 → Open
in Browser**. Each Codespace has its own preview address; an older Codespace's
URL does not point at the new one.

The review configuration explicitly sets port 8080 to **HTTP**, matching Flask.
GitHub supplies HTTPS for the browser connection. If this configuration was
updated after your Codespace was created, pull the branch, stop the app, and use
**Ctrl+Shift+P → Codespaces: Rebuild Container** once to apply it. This preserves
the review database; do not delete the Codespace or its database volume.

If a connection still fails, run this in a second terminal while the app is
running:

```bash
curl -I http://127.0.0.1:8080
```

An `HTTP/1.1 200 OK` response confirms the app is reachable locally. If the
browser still cannot connect and refreshing it produces no Flask request log,
the request is failing before it reaches the app. Record the browser's exact
error and check the Ports entry's HTTP protocol and preview address. Explicit
HTTP prevents protocol mismatches; it cannot repair every GitHub forwarding
failure. A refused local connection means the app is not listening on 8080;
check the running terminal for startup errors. A local 500 response instead
needs the Flask error log.

### Setup did not complete

From the repository directory, run:

```bash
bash .devcontainer/setup.sh
```

This preserves an existing review database; it does not reset your sample data.
If it reports that the PostgreSQL service is unavailable, use **Codespaces:
Rebuild Container**, wait for setup to finish, and try again.

Use a fresh Codespace without an `env.py` file. The setup refuses that file and
unexpected database settings because the application imports `env.py`
automatically. The supplied configuration already provides the review settings.

The preview creates a fresh schema directly from the current models. It does not
replay or stamp the historical migration chain. Do not use this setup procedure
for the live database, or run migration upgrades against this disposable preview.
It is intended for reviewing app behavior; the live release migration procedure
is documented separately in [owner-analysis-deployment.md](owner-analysis-deployment.md).
