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

-- ONE statement debit per card per month. The issuer also posts small separate debits
-- from the same account, under a description identical to the statement's: ~₪6 the day
-- before or after every monthly חיוב, plus the odd ₪59. (NOT דמי כרטיס — that is ₪17.90
-- and is charged on the card side, not here.) Whatever they are, matching on issuer name
-- alone swallowed them as statement debits and dropped them out of spend entirely — they
-- are real money leaving the account, and no card statement arrives twice in a month.
--
-- The largest debit of the month wins, which needs no threshold to tune: a statement is
-- three orders of magnitude above a fee.
-- ponytail: two cards from one issuer on one bank account share a description, so only
-- the larger statement would be excluded — split on the card suffix if that ever happens
qualify row_number() over (
    partition by account_id, raw_description, date_trunc('month', posted_date)
    order by abs(amount) desc
) = 1
