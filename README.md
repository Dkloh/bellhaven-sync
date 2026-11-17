# Bellhaven ownership reconciliation

A local Python scraper, deterministic matcher and approval-controlled Flask review app. The daily job only proposes. Every remote mutation requires an explicit reviewer decision through the app. No paid API keys or LLM calls in the pipeline.

## Run

Python 3.11+:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# Edit .env to supply your CRM sandbox token. Do not commit it.
.venv/bin/python sync.py
.venv/bin/python app.py
```

Open http://127.0.0.1:3000. Expand evidence, examine before/after fields and financial history, enter your reviewer name and rationale, then approve or reject each proposal. Applied and rejected tabs preserve decisions; confident matches need no write. Rejected changes are never applied automatically. The app binds to loopback, checks Host, escapes source content and uses session CSRF tokens. Do not expose this development app publicly.

Run tests: `.venv/bin/python -m pytest -q`.

## Discovery and matching

Crawl all directory pages and detail links from the homepage and about page. The homepage-only Findlay link matters: 34 directory entries plus Findlay = 35. Persist raw HTML, source URLs, timestamps, structured locations and CRM snapshots. Fail closed on missing/unparseable details or incomplete count. CRM pagination is explicit.

Compare across ALL CRM accounts, not just Bellhaven children. Normalize street suffixes, directions and punctuation; retain ZIP strings. Match normalized street + city/state, or exact name + city/state (to catch PO boxes). Street match ranks above name. Current Bellhaven copy ranks above former-brand copies; revenue-bearing copy is the next preference; equal candidates use stable ID order and remain visible for review. No fuzzy name-only cross-city matches. Hudson Amberly Manor and New Albany Union Square must not match misleading CRM names at other addresses.

Preserve equivalent street abbreviations. Map website rehab/nursing to Skilled Nursing and Memory Support to Memory Care; preserve mixed offerings as the full website string. Propose substantive fields and official names. Review may reject a cosmetic name change without losing the match.

Duplicate proposals retain the selected survivor and mark losers Inactive with `duplicate_of_account` and an explanatory note. Parent and financial history on losers remain. Shared address is evidence, not universal proof: inspect care offerings and candidate details. Kettering has three same-address, zero-revenue skilled-nursing records with no contacts; survivor selection is deterministic and documented, not a hidden certainty.

Not-listed accounts are marked Needs Review with a note, retaining parent. Website absence cannot establish a sale or closure. Sandusky's co-located Millstone account is a lead for follow-up, not enough to move a revenue/AR-bearing historical account.

## Billing SOP and restart safety

At review and again immediately before writing, inspect lifetime_revenue and outstanding_ar. When both are positive, create a successor under Bellhaven and PATCH only `chow_current_account` on the old account. Old account fields are otherwise preserved. With no revenue or no AR, re-parent directly. Marietta and Tiffin exercise the protected path.

SQLite stores content-derived proposal identities, decision, reviewer, rationale, timestamp, each completed API step and response. Observation timestamps do not change proposal identity. Approved and rejected decisions survive reruns; changed proposed values can create a genuinely new proposal. Preserve the entire `data/` directory; never clear it between scheduled runs. An approved-but-incomplete item can be resumed from the Approved tab.

Each create carries a unique proposal marker in its note. Before retrying a POST, reconcile against all CRM accounts for that marker. Persist every successful step. This recovers a successful remote create even if the local response/journal was interrupted. Patches detect already-applied values and stale reviewed fields. An OS file lock serializes app writers; cron uses its own pipeline lock. External CRM writers cannot be made transactional because this API has no conditional writes or documented idempotency keys; a narrow concurrent-write race remains. Do not use multiple independently copied ledgers for one sandbox.

## Daily operation

See `schedule/crontab`. Install on a persistent host, adjust `/opt/bellhaven-sync`, keep `.env` private and back up SQLite. Cron only discovers; a reviewer performs writes. Never schedule `review_session.py`: it documents the one-off AI review performed for this assessment and contains specific decisions, not a production approval policy.

## Submission artifacts

`data/accounts-before.json`, `accounts-latest.json`, `locations.json`, `review-session.json`, `verification.json`, raw HTML and `ledger.sqlite` provide the evidence and actual decision history. The included files contain fictional sandbox records and the decision ledger. The CRM token and virtual environment are excluded. See WRITEUP.md for the approach and limitations.
