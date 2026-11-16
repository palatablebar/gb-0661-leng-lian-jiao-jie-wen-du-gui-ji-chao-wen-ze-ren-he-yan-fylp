import json
from decimal import Decimal
from app import store
from app.modules.corrections.schema import parse_correction

def payload(**kw):
    base={'probe':'P1','offset':'-0.8','start':'2026-11-02T09:00:00+08:00','end':'2026-11-02T09:40:00+08:00','note':'漂移修正段 CAL-2026-1116'}
    base.update(kw);return base

def corrected(resp):
    return {s['shipment'] for s in resp['shipments'] if s['corrected']}

def test_partial_restore(client):
    before=store.latest()['manifest']['run_id']
    r=client.post('/api/corrections',json=payload());assert r.status_code==200
    body=r.json();assert body['summary']=={'corrected':3,'retained':5}
    assert corrected(body)=={'00002','00003','00004'}
    assert body['run_id']!=before;assert len(store.history())==2
    assert store.latest()['manifest']['run_id']==body['run_id']

def test_resubmit_no_new_batch(client):
    first=client.post('/api/corrections',json=payload()).json()
    second=client.post('/api/corrections',json=payload())
    assert second.status_code==200;assert second.json()['run_id']==first['run_id']
    assert second.json()['reused'] is True;assert len(store.history())==2

def test_failed_apply_keeps_old(client):
    before=store.latest()['manifest']['run_id'];count=len(store.history())
    assert client.post('/api/corrections',json=payload(end='2026-11-02T08:00:00+08:00')).status_code==422
    assert client.post('/api/corrections',json=payload(probe='P9')).status_code==422
    assert client.post('/api/corrections',json=payload(offset='推测值')).status_code==422
    assert client.post('/api/corrections',json=payload(offset='NaN')).status_code==422
    assert store.latest()['manifest']['run_id']==before;assert len(store.history())==count

def test_originals_and_review_preserved(client):
    base=store.latest();rid=base['manifest']['run_id']
    assert client.post('/api/batches/review',json={'run_id':rid,'version':base['version']}).status_code==200
    client.post('/api/corrections',json=payload())
    with store.connect() as c:
        row=c.execute('SELECT payload,reviewed FROM runs WHERE id=?',(rid,)).fetchone()
    kept=json.loads(row['payload'])
    assert row['reviewed']==1;assert kept['intake']['accepted']==base['intake']['accepted']
    assert kept['calculate']['totals']==base['calculate']['totals']

def test_correction_shifts_only_window(client):
    before={r['line']:r['temperature'] for r in store.latest()['contract']['rows']}
    client.post('/api/corrections',json=payload())
    after={r['line']:r['temperature'] for r in store.latest()['contract']['rows']}
    assert before.keys()==after.keys()
    assert after[2]=='3.2' and before[2]=='4'      # 09:00 窗口内下修
    assert after[7]=='4' and before[7]=='4'        # 09:40 半开窗口之外不动
    assert after[8]=='2' and before[8]=='2'        # 10:00 窗口之外不动

def test_retained_basis_evidence(client):
    body=client.post('/api/corrections',json=payload()).json()
    basis={s['shipment']:s['basis'] for s in body['shipments']}
    assert '第4行' in basis['00001'] and '第51行' in basis['00001']
    assert '缺测' in basis['00006'] and '第34行' in basis['00006']
    assert '第57行' in basis['00007'] and '第58行' in basis['00008']
    assert '第55行' in basis['00005']
    for s in body['shipments']:
        if not s['corrected']:assert all(o.get('pending') for o in s['owners'])

def test_settlement_conservation(client):
    base=store.latest()['calculate']['owners']
    body=client.post('/api/corrections',json=payload()).json()
    st=body['settlement'];assert st['balanced'] is True
    t=st['totals']
    assert abs(Decimal(t['coverage'])-sum(Decimal(t[k]) for k in ('normal','excess','unknown')))<=Decimal('0.00001')
    for f in ('coverage','normal','excess','unknown','degree_minutes'):
        assert abs(Decimal(t[f])-sum(Decimal(r[f]) for r in st['owners']))<=Decimal('0.00001')
    retained={r['shipment'] for r in st['owners'] if r['source']=='旧账'}
    assert retained=={'00001','00005','00006','00007','00008'}
    old={ (o['shipment'],o['owner']):o for o in base }
    for r in st['owners']:
        if r['source']=='旧账':assert old[(r['shipment'],r['owner'])]['degree_minutes']==r['degree_minutes']
        else:assert old[(r['shipment'],r['owner'])]['degree_minutes']!=r['degree_minutes']

def test_chain_and_overlap(client):
    a=client.post('/api/corrections',json=payload()).json()
    b=client.post('/api/corrections',json=payload(probe='P2',offset='0.3')).json()
    assert b['run_id']!=a['run_id'];assert len(b['corrections'])==2;assert len(store.history())==3
    again=client.post('/api/corrections',json=payload()).json()
    assert again['run_id']==b['run_id'] and again['reused'] is True;assert len(store.history())==3
    clash=client.post('/api/corrections',json=payload(offset='-0.5'))
    assert clash.status_code==409 and clash.json()['code']=='CORRECTION_OVERLAP'

def test_get_correction(client):
    assert client.get('/api/corrections').status_code==404
    client.post('/api/corrections',json=payload())
    r=client.get('/api/corrections');assert r.status_code==200
    assert r.json()['latest']['probe']=='P1'

def test_review_page_explains(client):
    client.post('/api/corrections',json=payload())
    html=client.get('/batches').text
    for token in ['已修正','保留旧账','待证实','今日结算账','00002','00006','漂移修正段']:
        assert token in html

def test_parse_correction_units():
    import pytest
    from app.errors import RuleError
    c=parse_correction(payload(),{'P1':'0'})
    assert c['offset']=='-0.8' and len(c['id'])==20
    with pytest.raises(RuleError):parse_correction(payload(start='2026-11-02T09:00:00'),{'P1':'0'})
