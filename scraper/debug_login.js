// temporary: print the URL FIBI lands on after login, to fix the possibleResults regexes
import { createScraper, CompanyTypes } from "israeli-bank-scrapers";
const s = createScraper({
  companyId: CompanyTypes.beinleumi,
  startDate: new Date(process.env.KASPION_START_DATE),
  showBrowser: process.env.KASPION_SHOW_BROWSER === "1",
});
const orig = s.getLoginOptions.bind(s);
s.getLoginOptions = (c) => {
  const o = orig(c);
  // a function condition is awaited with the landed URL; log it, then decline to match
  o.possibleResults.SUCCESS.push(async ({ value }) => {
    console.error("LANDED ON: " + value);
    return false;
  });
  return o;
};
const r = await s.scrape(JSON.parse(process.env.KASPION_CREDENTIALS));
console.error("result: " + JSON.stringify({ success: r.success, errorType: r.errorType }));
