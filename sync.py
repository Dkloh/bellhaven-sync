"""Bellhaven discovery, evidence matching, and durable approval ledger."""
import os,json,re,hashlib,sqlite3,urllib.request,time
from pathlib import Path
from datetime import datetime,timezone
from bs4 import BeautifulSoup
ROOT=Path(__file__).parent
BASE=os.environ.get('CRM_BASE','https://analyst-assessment-production.up.railway.app')
DATA=Path(os.environ.get('SYNC_DATA',str(ROOT/'data'))); DATA.mkdir(exist_ok=True)
if (ROOT/'.env').exists():
 for line in (ROOT/'.env').read_text().splitlines():
  k,_,v=line.partition('=');os.environ.setdefault(k,v)
def now(): return datetime.now(timezone.utc).isoformat()
def api(path,method='GET',body=None):
 req=urllib.request.Request(BASE+'/api/v1'+path,data=None if body is None else json.dumps(body).encode(),method=method,headers={'Authorization':'Bearer '+os.environ['CRM_TOKEN'],'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
def accounts():
 result=[];page=1
 while True:
  d=api(f'/accounts?page={page}&page_size=100');result+=d['data']
  if len(result)>=d['total']:return result
  if not d['data']:raise RuntimeError('Incomplete pagination')
  page+=1
def web(path):
 with urllib.request.urlopen(BASE+path,timeout=30) as r:text=r.read().decode()
 (DATA/('source-'+hashlib.sha256(path.encode()).hexdigest()[:12]+'.html')).write_text(text)
 return BeautifulSoup(text,'html.parser')
def scrape():
 todo=['/','/about','/communities'];seen=set();locations=[];advertised=None
 while todo:
  path=todo.pop(0)
  if path in seen:continue
  seen.add(path);s=web(path)
  for a in s.select('a[href]'):
   href=a['href']
   if href.startswith('/communities') and href not in seen:todo.append(href)
  if path=='/':
   m=re.search(r'serve (\d+) communities',s.get_text());advertised=int(m[1]) if m else None
  if not re.match(r'/communities/[^/?]+$',path):continue
  fields={dt.get_text(strip=True):dt.find_next_sibling('dd') for dt in s.select('dt')}
  if 'Address' not in fields:raise ValueError('Missing address '+path)
  addr=list(fields['Address'].stripped_strings);m=re.fullmatch(r'(.+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)',addr[-1])
  if not m:raise ValueError('Unparsed address '+path)
  locations.append(dict(name=s.h1.get_text(strip=True),billing_street=addr[0],billing_city=m[1],billing_state=m[2],billing_zip=m[3],care_type=fields['Care Offerings'].get_text(' / ',strip=True),source_url=BASE+path,evidence=s.select_one('.wrap').get_text(' ',strip=True),observed_at=now()))
 if advertised and len(locations)!=advertised:raise RuntimeError(f'Completeness guard: found {len(locations)} expected {advertised}')
 if len(locations)<30:raise RuntimeError('Directory unexpectedly small; stop before proposing removals')
 return sorted(locations,key=lambda x:x['name'])
def norm(s):
 s=re.sub(r'[^a-z0-9 ]',' ',str(s).lower());words=s.split();aliases={'street':'st','avenue':'ave','road':'rd','drive':'dr','lane':'ln','boulevard':'blvd','parkway':'pkwy','pike':'pk','northwest':'nw','north':'n','south':'s','east':'e','west':'w'}
 return ' '.join(aliases.get(w,w) for w in words)
def db():
 c=sqlite3.connect(DATA/'ledger.sqlite');c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT "pending",reviewer TEXT,reason TEXT,decided_at TEXT,result TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS steps (proposal TEXT, ordinal INTEGER, result TEXT, PRIMARY KEY(proposal,ordinal))');return c
def financial(a):return float(a.get('lifetime_revenue') or 0)>0 and float(a.get('outstanding_ar') or 0)>0
def changes(loc,a,parent):
 care={'Short-Term Rehabilitation & Nursing':'Skilled Nursing','Memory Support':'Memory Care'}.get(loc['care_type'],loc['care_type'])
 target={k:loc[k] for k in ['name','billing_street','billing_city','billing_state','billing_zip']};target.update(care_type=care,parent_id=parent,status='Active')
 # Preserve equivalent address abbreviations; correct actual content and postal errors.
 return {k:v for k,v in target.items() if (norm(a.get(k,''))!=norm(v) if k.startswith('billing_') else a.get(k)!=v)}
def generate(locs,acc):
 parents=[a for a in acc if a['name']=='Bellhaven Senior Living (Parent Account)']
 if len(parents)!=1:raise RuntimeError('Parent identity ambiguous')
 parent=parents[0]['account_id'];used=set();proposals=[];matches=[]
 def propose(kind,title,evidence,ops):
  payload=dict(kind=kind,title=title,evidence=evidence,operations=ops)
  key=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()[:24];payload['id']=key;proposals.append(payload)
 for loc in locs:
  candidates=[]
  for a in acc:
   if '(Parent Account)' in a['name'] or a.get('duplicate_of_account') or a.get('chow_current_account'):continue
   city=norm(loc['billing_city'])==norm(a['billing_city']) and loc['billing_state']==a['billing_state']
   street=norm(loc['billing_street'])==norm(a['billing_street'])
   name=norm(loc['name'])==norm(a['name'])
   if city and (street or name):candidates.append((int(street)*100+int(name)*30+int(a['parent_id']==parent)*10+int(float(a.get('lifetime_revenue') or 0)>0)*5,a))
  candidates.sort(key=lambda x:(-x[0],x[1]['account_id']))
  evidence={'website':loc,'candidates':[a for _,a in candidates],'rule':'Exact normalized street + city/state, or exact name + city/state. Street identity outranks name; Bellhaven current copy preferred, then revenue-bearing copy, then stable ID.'}
  if not candidates:
   target=changes(loc,{},parent);propose('missing',loc['name'],evidence,[dict(method='POST',body=target)]);continue
  a=candidates[0][1];used.update(c['account_id'] for _,c in candidates);delta=changes(loc,a,parent)
  # A new ownership account is allowed only after explicit approval; old billing fields remain untouched.
  if delta.get('parent_id') and financial(a):
   target=changes(loc,{},parent);target['note']='CHOW successor of '+a['account_id']
   propose('chow',loc['name'],evidence,[dict(method='POST',body=target),dict(method='PATCH',account_id=a['account_id'],before=a,body={'chow_current_account':'$created'})])
  elif delta:propose('fix',loc['name'],evidence,[dict(method='PATCH',account_id=a['account_id'],before=a,body=delta)])
  else:matches.append({'location':loc,'account_id':a['account_id'],'classification':'confident match'})
  for _,loser in candidates[1:]:
   # Shared address alone may represent distinct care units. Always review this explicit duplicate claim.
   note=('Duplicate of '+a['account_id']+'; same published facility address. Historical aliases retained in audit evidence.')
   propose('duplicate',loser['name'],evidence,[dict(method='PATCH',account_id=loser['account_id'],before=loser,body={'duplicate_of_account':a['account_id'],'status':'Inactive','note':((loser.get('note') or '')+'\n'+note).strip()})])
 for a in acc:
  if a['parent_id']==parent and a['account_id'] not in used and not a.get('duplicate_of_account') and not a.get('chow_current_account') and a['status']!='Needs Review':
   propose('not_listed',a['name'],{'account':a,'directory_urls':[l['source_url'] for l in locs],'rule':'Absent from complete website crawl. Absence alone does not prove a sale or closure; preserve parent and billing, flag Needs Review.'},[dict(method='PATCH',account_id=a['account_id'],before=a,body={'status':'Needs Review','note':((a.get('note') or '')+'\nNot listed on Bellhaven website as of '+now()[:10]+'. Ownership unconfirmed; verify before re-parenting or deactivation.').strip()})])
 return proposals,matches

def pipeline():
 locs=scrape();acc=accounts();(DATA/'locations.json').write_text(json.dumps(locs,indent=2));(DATA/'accounts-latest.json').write_text(json.dumps(acc,indent=2))
 if not (DATA/'accounts-before.json').exists():(DATA/'accounts-before.json').write_text(json.dumps(acc,indent=2))
 props,matches=generate(locs,acc);c=db();added=0
 # Evidence timestamps are not decision identity. Decisions survive repeated observation.
 for p in props:
  identity={'kind':p['kind'],'title':p['title'],'operations':[{k:v for k,v in op.items() if k!='before'} for op in p['operations']]}
  identity_text=re.sub(r'as of \d{4}-\d{2}-\d{2}', 'as of observation', json.dumps(identity,sort_keys=True))
  p['id']=hashlib.sha256(identity_text.encode()).hexdigest()[:24]
  added+=c.execute('INSERT OR IGNORE INTO proposals(id,payload) VALUES (?,?)',(p['id'],json.dumps(p))).rowcount
 c.commit();(DATA/'matches.json').write_text(json.dumps(matches,indent=2));return dict(locations=len(locs),accounts=len(acc),new_proposals=added,confident_matches=len(matches))
def _decide(pid,decision,reviewer,reason):
 if decision not in ('approve','reject') or not reviewer.strip() or not reason.strip():raise ValueError('Decision, reviewer and reason required')
 c=db();c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
 if not row:raise ValueError('Unknown proposal')
 if row['state'] in ('applied','rejected'):return dict(state=row['state'])
 if decision=='reject':
  if row['state']=='approved':raise RuntimeError('An approved operation may already have remote effects; resume it instead of rejecting')
  c.execute('UPDATE proposals SET state="rejected",reviewer=?,reason=?,decided_at=? WHERE id=?',(reviewer,reason,now(),pid));c.commit();return {'state':'rejected'}
 p=json.loads(row['payload'])
 # Record explicit approval durably BEFORE any remote mutation.
 c.execute('UPDATE proposals SET state="approved",reviewer=?,reason=?,decided_at=? WHERE id=?',(reviewer,reason,now(),pid));c.commit()
 created=None;results=[]
 try:
  for i,op in enumerate(p['operations']):
   done=c.execute('SELECT result FROM steps WHERE proposal=? AND ordinal=?',(pid,i)).fetchone()
   if done:
    result=json.loads(done[0]);created=result.get('account_id',created);results.append(result);continue
   body=dict(op['body'])
   if body.get('chow_current_account')=='$created':body['chow_current_account']=created
   if op['method']=='PATCH':
    current=api('/accounts/'+op['account_id']);before=op['before']
    fields=set(body)|{'parent_id','lifetime_revenue','outstanding_ar','duplicate_of_account','chow_current_account'}
    if all(current.get(k)==v for k,v in body.items()):result=current
    else:
     if any(current.get(k)!=before.get(k) for k in fields):raise RuntimeError('Stale evidence: CRM changed; refresh and review')
     if 'parent_id' in body and body['parent_id']!=current['parent_id'] and financial(current):raise RuntimeError('Billing SOP blocks reparent')
     result=api('/accounts/'+op['account_id'],'PATCH',body)
   else:
    marker='[bellhaven-sync:'+pid+']';body['note']=(body.get('note','')+' '+marker).strip()
    existing=[a for a in accounts() if marker in (a.get('note') or '')]
    if len(existing)>1:raise RuntimeError('Multiple recovery marker accounts')
    result=existing[0] if existing else api('/accounts','POST',body)
    created=result.get('account_id')
    if not created:raise RuntimeError('Create response missing account_id')
   c.execute('INSERT INTO steps VALUES (?,?,?)',(pid,i,json.dumps(result)));c.commit();results.append(result)
  c.execute('UPDATE proposals SET state="applied",result=? WHERE id=?',(json.dumps(results),pid));c.commit();return {'state':'applied','results':results}
 except Exception as e:
  c.execute('UPDATE proposals SET result=? WHERE id=?',(json.dumps({'error':str(e)}),pid));c.commit();raise
def decide(pid,decision,reviewer,reason):
 from filelock import FileLock
 # OS-backed locking on Windows, macOS and Linux; release even if a write fails.
 with FileLock(str(DATA/'write.lock'), timeout=60):
  return _decide(pid,decision,reviewer,reason)
if __name__=='__main__':print(json.dumps(pipeline(),indent=2))
