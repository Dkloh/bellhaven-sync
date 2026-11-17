import secrets,json,threading
from flask import Flask,request,render_template_string,session,redirect,url_for,abort
import sync
app=Flask(__name__);app.secret_key=secrets.token_hex(32);lock=threading.Lock()
PAGE='''<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Bellhaven • Ownership review</title><style>
body{margin:0;background:#f4f6f5;color:#17372d;font:15px system-ui}header{background:#173f33;color:white;padding:26px 5%;display:flex;justify-content:space-between}main{max-width:1150px;margin:35px auto;padding:0 20px}h1{font:36px Georgia;margin:8px 0}h2{font:25px Georgia}a{color:#28765d}header a{color:white}.stats{display:flex;gap:15px;flex-wrap:wrap;margin:25px 0}.stats a{background:white;padding:18px;border:1px solid #dbe3de;text-decoration:none;border-radius:9px}.card{background:white;border:1px solid #dbe3de;border-radius:12px;padding:25px;margin:20px 0}.tag{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#647c70}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{text-align:left;padding:10px;border-bottom:1px solid #e5ebe7;vertical-align:top;overflow-wrap:anywhere}th{font-size:12px;text-transform:uppercase;color:#718178}button{padding:12px 20px;border:0;border-radius:5px;background:#236c50;color:white;cursor:pointer;font-weight:bold}button.reject{background:#8a443f}input{padding:12px;border:1px solid #bbcabe;border-radius:5px;margin:5px;max-width:90%}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;color:#456153}summary{cursor:pointer;padding:10px 0}.notice{background:#fff0c7;padding:18px;border-radius:8px}.empty{padding:60px;text-align:center}nav{margin:16px 0}</style>
<header><b>BELLHAVEN / DATA OPERATIONS</b><span>Approval-controlled CRM sync</span></header><main><div class="tag">Ownership reconciliation</div><h1>Review the evidence. Keep the history.</h1><p>Each decision is recorded. Approving writes the displayed operations to the CRM; rejecting records a decision without a CRM write.</p>
<div class="stats">{% for state,n in counts %}<a href="/?state={{state}}"><b>{{n}}</b> {{state}}</a>{% endfor %}<a href="/?state=all">All decisions</a><a href="/matches">Confident matches</a></div>
{% if error %}<p class="notice">{{error}}</p>{% endif %}
{% for p in proposals %}<article class="card" id="{{p.id}}"><span class="tag">{{p.kind}} · {{p.state}} · {{p.id}}</span><h2>{{p.title}}</h2>
{% if p.evidence.website %}{% set w=p.evidence.website %}<p><a href="{{w.source_url}}" target="_blank" rel="noopener">Published community ↗</a> · {{w.billing_street}}, {{w.billing_city}}, {{w.billing_state}} {{w.billing_zip}}<br>{{w.care_type}}</p><p>{{w.evidence}}</p>{% endif %}
<p>{{p.evidence.rule}}</p>
{% for op in p.operations %}<b>{{op.method}} {{op.account_id or 'New facility account'}}</b><table><tr><th>Field</th><th>Current</th><th>Proposed</th></tr>{% for k,v in op.body.items() %}<tr><td>{{k}}</td><td>{{op.get('before',{}).get(k,'—')}}</td><td>{{v}}</td></tr>{% endfor %}</table>{% if op.before %}<p>Billing check: lifetime revenue <b>{{op.before.lifetime_revenue}}</b> · outstanding AR <b>{{op.before.outstanding_ar}}</b></p>{% endif %}{% endfor %}
<details><summary>Full source evidence and CRM candidates</summary><pre>{{p.evidence|tojson(indent=2)}}</pre></details>
{% if p.state in ['pending','approved'] %}<form method="post" action="/decide/{{p.id}}"><input type="hidden" name="csrf" value="{{csrf}}"><input name="reviewer" placeholder="Reviewer" value="{{reviewer}}" required aria-label="Reviewer"><input name="reason" placeholder="Decision rationale" required size="55" aria-label="Decision rationale"><button name="decision" value="approve">Approve & write</button> {% if p.state=='pending' %}<button class="reject" name="decision" value="reject">Reject</button>{% endif %}</form>{% else %}<p><b>{{p.state}}</b> by {{p.reviewer}} · {{p.reason}} · {{p.decided_at}}</p>{% endif %}
{% if p.result %}<details><summary>CRM result / recovery status</summary><pre>{{p.result}}</pre></details>{% endif %}</article>{% else %}<div class="card empty">No items in this view.</div>{% endfor %}</main></html>'''
@app.before_request
def local_only():
 if request.host.split(':')[0] not in ('127.0.0.1','localhost'):abort(403)
 if 'csrf' not in session:session['csrf']=secrets.token_hex(24)
@app.get('/')
def index():
 c=sync.db();state=request.args.get('state','pending');rows=c.execute('SELECT * FROM proposals ORDER BY rowid').fetchall();ps=[]
 for row in rows:
  if state!='all' and row['state']!=state:continue
  p=json.loads(row['payload']);p.update({k:row[k] for k in ['state','reviewer','reason','decided_at','result']});ps.append(p)
 counts=[(s,sum(r['state']==s for r in rows)) for s in ['pending','approved','applied','rejected']]
 return render_template_string(PAGE,proposals=ps,counts=counts,csrf=session['csrf'],reviewer=session.get('reviewer',''),error=request.args.get('error'))
@app.post('/decide/<pid>')
def decide(pid):
 if not secrets.compare_digest(request.form.get('csrf',''),session['csrf']):abort(403)
 try:
  with lock:sync.decide(pid,request.form['decision'],request.form['reviewer'],request.form['reason'])
  session['reviewer']=request.form['reviewer'];return redirect('/')
 except Exception as e:return redirect(url_for('index',error=str(e)))
@app.get('/matches')
def matches():
 return '<h1>Confident matches — no change needed</h1><a href="/">Back</a><pre>'+__import__('html').escape((sync.DATA/'matches.json').read_text())+'</pre>'
if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=3000);parser.add_argument('--host',default='127.0.0.1');args,_=parser.parse_known_args()
 app.run(host=args.host,port=args.port,debug=False)
