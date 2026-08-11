// Reads config from env (never argv — argv leaks into process lists).
// Prints normalized JSON rows (raw.transactions contract) to stdout.
import { createScraper, CompanyTypes } from "israeli-bank-scrapers";

const companyId = process.env.KASPION_COMPANY;                    // e.g. "leumi", "max", "isracard"
const credentials = JSON.parse(process.env.KASPION_CREDENTIALS);  // decrypted by the Python caller
const startDate = new Date(process.env.KASPION_START_DATE);
const accountType = process.env.KASPION_ACCOUNT_TYPE;             // "bank" | "credit_card"

const scraper = createScraper({
  companyId: CompanyTypes[companyId] ?? companyId,
  startDate,
  combineInstallments: false,
  showBrowser: false,
});

const result = await scraper.scrape(credentials);
if (!result.success) {
  console.error(JSON.stringify({ error: result.errorType, message: result.errorMessage }));
  process.exit(1);
}

const rows = [];
for (const account of result.accounts) {
  for (const txn of account.txns) {
    rows.push({
      source_id: txn.identifier ?? null, // prefer the bank-provided id
      account_id: `${companyId}-${account.accountNumber}`,
      account_type: accountType,
      posted_date: txn.date.slice(0, 10),
      // israeli-bank-scrapers: chargedAmount is negative for charges.
      // VERIFY the sign convention per institution after the first real scrape;
      // if a source reports charges as positive, negate HERE, never downstream.
      amount: txn.chargedAmount,
      currency: txn.originalCurrency || "ILS",
      raw_description: txn.description,
      source: companyId,
    });
  }
}
process.stdout.write(JSON.stringify(rows));
