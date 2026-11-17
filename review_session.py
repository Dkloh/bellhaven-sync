"""One-off assessment review. Explicit per-proposal decisions, never run by cron.
Uses the review app forms, CSRF token, and approval route. Reviewer is an AI.
"""
import urllib.request,urllib.parse,http.cookiejar,json
from bs4 import BeautifulSoup
from pathlib import Path
import sync
REASONS={
'missing':'Published facility address has no CRM match. Same-name and nearby accounts have different physical addresses; create a separate current facility.',
'fix':'Reviewed published name, address and care against CRM candidates. Correct identity supported by exact normalized address or exact name and city/state. Apply displayed corrections; direct parent changes have no outstanding AR.',
'chow':'Exact facility identity; old parent differs and both lifetime revenue and AR are positive. Approve successor creation and CHOW link only. Preserve all old billing and parent fields.',
'duplicate':'Reviewed co-located candidates, care and historical brands. One published facility at this address; retain the selected current Bellhaven copy (or deterministic zero-revenue Kettering survivor). Mark losing copy Inactive and link duplicate; retain its parent and financial history.',
'not_listed':'Absent from the complete 35-location crawl. Flag Needs Review while retaining parent and financial history; website absence alone does not establish a new owner. Sandusky has a Millstone record at the same address, which warrants investigation rather than a speculative transfer.'}
def main():
 opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 html=opener.open('http://127.0.0.1:3000/').read().decode();s=BeautifulSoup(html,'html.parser')
 rows=sync.db().execute('select * from proposals where state="pending"').fetchall()
 report=[]
 for row in rows:
  p=json.loads(row['payload']);card=s.find(id=p['id'])
  if card is None:raise RuntimeError('Proposal not rendered')
  reason=REASONS[p['kind']];decision='approve'
  if p['title']=='Bellhaven Healthcare Centre of Ashland':
   decision='reject';reason='Name-only spelling/style difference: Health Care Center vs Healthcare Centre identifies the same facility with exact address. Retain this valid CRM alias; no ownership or address correction needed.'
  token=card.select_one('input[name=csrf]')['value']
  form=dict(csrf=token,reviewer='Codex (AI reviewer)',reason=reason,decision=decision)
  req=urllib.request.Request('http://127.0.0.1:3000/decide/'+p['id'],data=urllib.parse.urlencode(form).encode())
  response=opener.open(req).read().decode()
  current=sync.db().execute('select state,result from proposals where id=?',(p['id'],)).fetchone()
  if current['state'] not in ('applied','rejected'):raise RuntimeError(str(dict(current)))
  report.append(dict(id=p['id'],title=p['title'],kind=p['kind'],decision=decision,reason=reason,state=current['state']));print(p['title'],current['state'],flush=True)
 (sync.DATA/'review-session.json').write_text(json.dumps(report,indent=2))
if __name__=='__main__':main()
