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
  // KASPION_SHOW_BROWSER=1 opens a visible browser for debugging a failing login —
  // the only way to see a verification/OTP step the library can't report back.
  showBrowser: process.env.KASPION_SHOW_BROWSER === "1",
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
      //
      // A purchase the card company has not booked yet (Max's "עסקאות שטרם נקלטו")
      // arrives with chargedAmount 0 and the real figure in originalAmount — taking
      // the 0 put a ₪0 row on the dashboard for a real 160₪ swim. Only when the
      // original is in shekels: a foreign originalAmount is not the shekel charge,
      // and a wrong number is worse than a visible zero.
      // An ABSENT currency is not a promise of shekels, so it falls through to the 0
      // as well: a visible zero is honest, a foreign figure printed as ₪ is not.
      amount: (txn.chargedAmount === 0 && txn.originalAmount
               && ["ILS", "₪"].includes(txn.originalCurrency)
               ? txn.originalAmount : txn.chargedAmount),
      // chargedAmount is always in the account's own currency (ILS for Israeli cards),
      // even when the underlying purchase was foreign — never tag it with originalCurrency,
      // that describes txn.originalAmount (unused here), not chargedAmount.
      currency: "ILS",
      raw_description: txn.description,
      source: companyId,
    });
  }
}
process.stdout.write(JSON.stringify(rows));
