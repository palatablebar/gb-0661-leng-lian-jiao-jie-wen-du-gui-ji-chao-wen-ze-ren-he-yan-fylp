import base64,json
from app import store
from app.config import SAMPLES
from app.errors import RuleError
from app.pipeline import execute
from app.modules.corrections.schema import parse_correction,conflicts_with
from app.modules.corrections.decide import decide_shipments,build_settlement

def apply_correction(payload):
    base=store.latest()
    if not base:raise RuleError('NO_BASE','没有可修正的基准批次',409)
    if not base['reconcile']['balanced']:raise RuleError('UNBALANCED','基准批次对账不平，不能修正',409)
    calibrations=json.loads((SAMPLES/'calibrations.json').read_bytes())
    correction=parse_correction(payload,calibrations)
    prior=list(base.get('correction',{}).get('corrections',[]))
    if correction['id'] in {c['id'] for c in prior}:corrections=prior
    else:
        if any(conflicts_with(c,correction) for c in prior):raise RuleError('CORRECTION_OVERLAP','同一探头修正窗口重叠',409)
        corrections=prior+[correction]
    if 'input_b64' not in base:raise RuleError('NO_INPUT','基准批次缺少原始采样，无法修正',409)
    raw=base64.b64decode(base['input_b64'])
    params=base['manifest']['parameters']
    candidate=execute(raw,params['threshold'],int(params['max_gap']),corrections)
    if not candidate['reconcile']['balanced']:raise RuleError('UNBALANCED','修正后对账不平，已保留旧版',409)
    decisions=decide_shipments(base,candidate,correction,params['threshold'])
    settlement=build_settlement(base,candidate,decisions)
    n_c=sum(1 for d in decisions if d['corrected']);n_r=len(decisions)-n_c
    candidate['correction']={'corrections':corrections,'latest':correction,'base_run_id':base['manifest']['run_id'],
        'verdict':f"裁决：先采用可证实部分。{n_c}批完整还原，按修正段重算入账；{n_r}批无法完整还原，保留旧账并将窗口内责任分钟标记待证实，不按推测温度入账。",
        'summary':{'corrected':n_c,'retained':n_r},'shipments':decisions,'settlement':settlement}
    saved=store.save(candidate)
    out=dict(saved['correction'])
    out.update({'run_id':saved['manifest']['run_id'],'version':saved['version'],'reused':saved['reused']})
    return out
