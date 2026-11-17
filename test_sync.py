import json
import pytest
import sync

def account(**kw):
 a=dict(account_id='a',name='Bellhaven of Test',parent_id='old',billing_street='10 Main Street',billing_city='Test',billing_state='OH',billing_zip='12345',care_type='Assisted Living',status='Active',lifetime_revenue=100,outstanding_ar=10,note='',chow_current_account='',duplicate_of_account='');a.update(kw);return a

def location():return dict(name='Bellhaven of Test',billing_street='10 Main St',billing_city='Test',billing_state='OH',billing_zip='12345',care_type='Assisted Living',source_url='https://example.test',evidence='published')
def parent():return account(account_id='p',name='Bellhaven Senior Living (Parent Account)',parent_id='')
def test_chow_preserves_old_account():
 ps,_=sync.generate([location()],[parent(),account()]);p=ps[0]
 assert p['kind']=='chow'
 assert p['operations'][1]['body']=={'chow_current_account':'$created'}
 assert p['operations'][0]['body']['parent_id']=='p'
@pytest.mark.parametrize('rev,ar',[(0,100),(100,0),(0,0)])
def test_direct_reparent_when_billing_permits(rev,ar):
 ps,_=sync.generate([location()],[parent(),account(lifetime_revenue=rev,outstanding_ar=ar)])
 assert ps[0]['kind']=='fix';assert ps[0]['operations'][0]['body']=={'parent_id':'p'}
def test_same_name_other_state_is_not_match():
 ps,_=sync.generate([location()],[parent(),account(billing_state='MI')]);assert ps[0]['kind']=='missing'
def test_not_listed_preserves_parent():
 ps,_=sync.generate([],[parent(),account(parent_id='p')]);assert ps[0]['operations'][0]['body']['status']=='Needs Review';assert 'parent_id' not in ps[0]['operations'][0]['body']
def test_rejected_decision_survives_rerun(tmp_path,monkeypatch):
 monkeypatch.setattr(sync,'DATA',tmp_path);monkeypatch.setattr(sync,'scrape',lambda:[location()]);monkeypatch.setattr(sync,'accounts',lambda:[parent()])
 assert sync.pipeline()['new_proposals']==1
 pid=sync.db().execute('select id from proposals').fetchone()[0]
 sync.decide(pid,'reject','Test','Insufficient evidence')
 assert sync.pipeline()['new_proposals']==0
 assert sync.db().execute('select state from proposals').fetchone()[0]=='rejected'
def test_write_time_financial_guard(tmp_path,monkeypatch):
 monkeypatch.setattr(sync,'DATA',tmp_path)
 old=account(lifetime_revenue=0,outstanding_ar=0);ps,_=sync.generate([location()],[parent(),old]);p=ps[0];c=sync.db();c.execute('insert into proposals(id,payload) values (?,?)',(p['id'],json.dumps(p)));c.commit()
 monkeypatch.setattr(sync,'api',lambda *args,**kwargs:account())
 with pytest.raises(RuntimeError,match='Stale evidence'):sync.decide(p['id'],'approve','Test','Reviewed')
def test_post_recovery_does_not_create_twice(tmp_path,monkeypatch):
 monkeypatch.setattr(sync,'DATA',tmp_path);p={'id':'recover','operations':[{'method':'POST','body':{'name':'New'}}]};c=sync.db();c.execute('insert into proposals(id,payload) values (?,?)',(p['id'],json.dumps(p)));c.commit()
 monkeypatch.setattr(sync,'accounts',lambda:[{'account_id':'existing','note':'[bellhaven-sync:recover]'}])
 monkeypatch.setattr(sync,'api',lambda *args:pytest.fail('Must not repeat POST'))
 assert sync.decide('recover','approve','Test','Retry')['state']=='applied'

def test_app_requires_csrf_and_reject_never_calls_crm(tmp_path,monkeypatch):
 import app
 monkeypatch.setattr(sync,'DATA',tmp_path)
 p={'id':'review','title':'Review me','kind':'fix','evidence':{'rule':'Test evidence'},'operations':[{'method':'PATCH','account_id':'a','before':account(),'body':{'name':'Updated'}}]}
 c=sync.db();c.execute('insert into proposals(id,payload) values (?,?)',(p['id'],json.dumps(p)));c.commit()
 monkeypatch.setattr(sync,'api',lambda *args:pytest.fail('Reject must not call CRM'))
 client=app.app.test_client();response=client.get('/',headers={'Host':'localhost'})
 assert response.status_code==200 and b'Review me' in response.data
 assert client.post('/decide/review',data={'decision':'approve'},headers={'Host':'localhost'}).status_code==403
 with client.session_transaction() as session:csrf=session['csrf']
 response=client.post('/decide/review',data={'csrf':csrf,'decision':'reject','reviewer':'Reviewer','reason':'Wrong facility'},headers={'Host':'localhost'},follow_redirects=True)
 assert response.status_code==200
 assert sync.db().execute('select state from proposals').fetchone()[0]=='rejected'

def test_repeated_approval_only_writes_once(tmp_path,monkeypatch):
 monkeypatch.setattr(sync,'DATA',tmp_path)
 a=account(lifetime_revenue=0,outstanding_ar=0);p={'id':'patch','operations':[{'method':'PATCH','account_id':'a','before':a.copy(),'body':{'parent_id':'p'}}]}
 c=sync.db();c.execute('insert into proposals(id,payload) values (?,?)',(p['id'],json.dumps(p)));c.commit();writes=[]
 def fake_api(path,method='GET',body=None):
  if method=='PATCH':writes.append(body);a.update(body)
  return a.copy()
 monkeypatch.setattr(sync,'api',fake_api)
 assert sync.decide('patch','approve','Reviewer','Reviewed')['state']=='applied'
 assert sync.decide('patch','approve','Reviewer','Retry')['state']=='applied'
 assert writes==[{'parent_id':'p'}]

def test_decision_lock_blocks_another_process(tmp_path,monkeypatch):
 import subprocess,sys
 from filelock import Timeout
 monkeypatch.setattr(sync,'DATA',tmp_path)
 def while_locked(*args):
  code='from filelock import FileLock, Timeout\nimport sys\ntry:\n with FileLock(sys.argv[1], timeout=0): pass\nexcept Timeout: sys.exit(23)\n'
  result=subprocess.run([sys.executable,'-c',code,str(tmp_path/'write.lock')],capture_output=True,text=True,timeout=10)
  assert result.returncode==23,result.stderr
  return {'state':'tested'}
 monkeypatch.setattr(sync,'_decide',while_locked)
 assert sync.decide('test','approve','Test','Lock test')=={'state':'tested'}

def test_decision_lock_releases_after_error(tmp_path,monkeypatch):
 from filelock import FileLock
 monkeypatch.setattr(sync,'DATA',tmp_path)
 def fail(*args):raise RuntimeError('Simulated CRM failure')
 monkeypatch.setattr(sync,'_decide',fail)
 with pytest.raises(RuntimeError,match='Simulated CRM failure'):
  sync.decide('test','approve','Test','Lock test')
 with FileLock(str(tmp_path/'write.lock'),timeout=0):pass
