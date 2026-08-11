"""Built-in knowledge: well-known Israeli merchants -> category, matched by substring.

This layer runs BEFORE any AI model (and even with --provider none), so common
merchants are always categorized correctly and for free. Keys are lowercase
substrings matched against the normalized merchant key.
"""
from __future__ import annotations

KNOWN: dict[str, str] = {
    # groceries
    "רמי לוי": "groceries", "שופרסל": "groceries", "יוחננוף": "groceries",
    "ויקטורי": "groceries", "יינות ביתן": "groceries", "אושר עד": "groceries",
    "טיב טעם": "groceries", "חצי חינם": "groceries", "am:pm": "groceries",
    "am pm": "groceries", "מגה בעיר": "groceries", "קרפור": "groceries",
    # restaurants & delivery
    "וולט": "restaurants", "wolt": "restaurants", "תן ביס": "restaurants",
    "10bis": "restaurants", "מקדונלד": "restaurants", "ארומה": "restaurants",
    "קפה גרג": "restaurants", "לנדוור": "restaurants", "ג'פניקה": "restaurants",
    "דומינו": "restaurants", "פיצה": "restaurants", "בורגר": "restaurants",
    "מסעד": "restaurants", "קפה": "restaurants",
    # transport & fuel
    "פז ": "transport", "סונול": "transport", "דור אלון": "transport",
    "רב קו": "transport", "פנגו": "transport", "pango": "transport",
    "gett": "transport", "yango": "transport", "חניון": "transport",
    "cellopark": "transport", "רכבת ישראל": "transport", "דלק מנטה": "transport",
    # housing & bills
    "חברת החשמל": "housing", "מי אביבים": "housing", "מקורות": "housing",
    "ארנונה": "housing", "ועד בית": "housing", "שכר דירה": "housing",
    "אמישראגז": "housing", "סופרגז": "housing", "בזק": "housing",
    "hot ": "housing", "פרטנר": "housing", "סלקום": "housing",
    # health
    "סופר פארם": "health", "גוד פארם": "health", "מכבי": "health",
    "כללית": "health", "לאומית": "health", "מאוחדת": "health", "בית מרקחת": "health",
    # subscriptions
    "netflix": "subscriptions", "spotify": "subscriptions", "icloud": "subscriptions",
    "youtube": "subscriptions", "apple.com": "subscriptions", "disney": "subscriptions",
    "google one": "subscriptions", "chatgpt": "subscriptions", "claude.ai": "subscriptions",
    # entertainment
    "סינמה סיטי": "entertainment", "יס פלנט": "entertainment", "רב חן": "entertainment",
    # clothing
    "zara": "clothing", "h&m": "clothing", "קסטרו": "clothing", "פוקס": "clothing",
    "רנואר": "clothing", "טרמינל": "clothing", "גולף": "clothing",
    # electronics
    "ksp": "electronics", "באג": "electronics", "אייבורי": "electronics",
    "lastprice": "electronics",
    # insurance
    "הפניקס": "insurance", "הראל ביטוח": "insurance", "מגדל ביטוח": "insurance",
    "כלל ביטוח": "insurance", "מנורה": "insurance", "ביטוח ישיר": "insurance",
    "aig": "insurance",
    # kids
    "גן ילדים": "kids", "צהרון": "kids", "משפחתון": "kids",
}


def match(merchant_key: str) -> str | None:
    """Return the category for a known merchant, or None if we don't know it."""
    for keyword, category in KNOWN.items():
        if keyword in merchant_key:
            return category
    return None
