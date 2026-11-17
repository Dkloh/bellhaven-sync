"""Read-only end-state verification against fresh CRM API responses."""
import json
import sync

def verify():
 current=sync.accounts();byid={a['account_id']:a for a in current};before=json.loads((sync.DATA/'accounts-before.json').read_text());old={a['account_id']:a for a in before};c=sync.db();checks=[]
 for row in c.execute('select * from proposals'):
  p=json.loads(row['payload'])
  if row['state']=='applied':
   results=json.loads(row['result']);created=None
   for op,result in zip(p['operations'],results):
    aid=op.get('account_id') or result['account_id'];actual=byid[aid]
    if op['method']=='POST':created=aid
    for field,value in op['body'].items():
     expected=created if value=='$created' else value
     if field=='note' and op['method']=='POST':expected=(expected+' [bellhaven-sync:'+p['id']+']').strip()
     assert actual[field]==expected,(p['title'],field,actual[field],expected)
   if p['kind']=='chow':
    aid=p['operations'][1]['account_id'];a=byid[aid]
    for k,v in old[aid].items():
     if k not in ('updated_at','chow_current_account'):assert a[k]==v,('Old account changed',aid,k)
   checks.append({'proposal':p['id'],'title':p['title'],'verified':True})
  elif row['state']=='rejected':
   for op in p['operations']:
    if op.get('account_id'):
     aid=op['account_id']
     for field in op['body']:assert byid[aid][field]==old[aid][field]
  else:raise AssertionError('Undecided proposal '+p['id'])
 for aid,a in old.items():
  assert byid[aid]['lifetime_revenue']==a['lifetime_revenue']
  assert byid[aid]['outstanding_ar']==a['outstanding_ar']
 rerun=sync.pipeline();assert rerun['new_proposals']==0,rerun
 states=dict(c.execute('select state,count(*) from proposals group by state').fetchall())
 report={'verified_at':sync.now(),'accounts_before':len(before),'accounts_after':len(current),'decisions':states,'billing_history_preserved':True,'chow_old_accounts_preserved':True,'rerun':rerun,'checks':checks}
 (sync.DATA/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='checks'},indent=2))
if __name__=='__main__':verify()
