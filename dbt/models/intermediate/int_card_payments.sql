-- Bank-side monthly card debits (חיוב). NOT pair-matched: the debit equals the
-- card's statement total, not any single transaction. Detected by issuer pattern.
select
    transaction_id,
    account_id,
    posted_date,
    amount,
    raw_description
from {{ ref('stg_transactions') }}
where account_type = 'bank'
  and amount < 0
  and (
      -- "חיוב <issuer>" — how most banks word the monthly card debit
      regexp_matches(raw_description, 'חיוב.*(מקס|ישראכרט|כאל|ויזה|אמריקן|לאומי קארד)')
      -- ONE ZERO names the issuer with no "חיוב" prefix at all, e.g.
      -- "מקס איט פיננסים/<account>" or "ישראכרט-דיירקט/<ref>/<card>". Missing these
      -- would count the whole card statement a second time on top of the card's
      -- own charges, so the issuer names are matched on their own too.
      or regexp_matches(raw_description, '(מקס איט|ישראכרט|לאומי קארד|כאל בע|אמריקן אקספרס)')
      -- FIBI/Beinleumi names no issuer at all, just "<last 4 digits> - כרטיסי אשראי לי"
      or raw_description like '%כרטיסי אשראי%'
  )
