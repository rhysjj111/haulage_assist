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
   port's Codespaces visibility **Private**, which is the default.

The app stays running in that terminal. Press **Ctrl+C** to stop it; run the same
command to start it again. Normal restarts and container rebuilds preserve the
review database and your edits. Deleting the Codespace deletes this preview.

## What to review

The setup output gives dated links relative to the day the sample data was
created. Open those paths on your preview's address:

| Example | What to look for |
| --- | --- |
| Complete example week | Clear financial summary, driver/truck views and an explicit review status. The seeded figures are £9,625 earnings, £3,128 employer wage cost, £1,490 fuel, £1,400 overheads and £3,607 estimated result. |
| Checks to practise | A missing day, missing payslip, missing fuel receipt and unusual job amount. Open **Review check**, inspect the week, then correct or explain it as appropriate. |
| Duplicate payslip example | Compare both entries before confirming a duplicate removal, or verify genuinely separate payslips with an explanation. |
| Previous month | Whole payroll weeks, monthly totals and review status. |
| Current partial week | Only entries due so far; later dates remain outside the figures. If you create the preview at a weekend, there may be no Working days yet. |
| Truck and overhead settings | Four sample trucks, with a dated allowance change from £350 to £400 per truck per week. These are demo amounts. |

Start at `/owner-analysis` or use the complete-week link from setup. Missing
financial information deliberately leaves the example issue week's profit
pending. Holiday/Absent records, a one-day truck exchange and the dated overhead
change provide other examples to inspect. Your edits affect only this preview.

## If setup needs retrying

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
