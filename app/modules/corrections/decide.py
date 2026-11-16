from collections import defaultdict
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from app.errors import RuleError
from app.reasons import REASONS
from app.modules.calculate.integral import excess,fmt
from app.modules.contract.normalize import instant
LOCAL=timezone(timedelta(hours=8))

def _window(correction):
    return datetime.fromisoformat(correction['start']),datetime.fromisoformat(correction['end'])

def _overlap(a,b,start,end):
    return datetime.fromisoformat(a)<end and datetime.fromisoformat(b)>start

def _raw_shipment_at(raw):
    if isinstance(raw,dict):return raw.get('shipment'),raw.get('at')
    if isinstance(raw,list) and len(raw)>2:return raw[0],raw[2]
    return None,None

def _in_window(at,start,end):
    try:return start<=instant(str(at))<end
    except RuleError:return True

def _hhmm(iso):
    return datetime.fromisoformat(iso).astimezone(LOCAL).strftime('%H:%M')

def _owner_totals(segments,threshold):
    totals=defaultdict(lambda:[Decimal(0),Decimal(0),Decimal(0)])
    for s in segments:
        t=totals[s['owner']];t[0]+=Decimal(s['minutes'])
        if s['left'] is not None:
            over,area=excess(s['left'],s['right'],s['minutes'],threshold);t[1]+=over;t[2]+=area
    return totals

def decide_shipments(base,candidate,correction,threshold):
    start,end=_window(correction);decisions=[]
    shipments=sorted({s['shipment'] for s in candidate['model']['segments']}|{s['shipment'] for s in base['model']['segments']})
    for ship in shipments:
        cand=[s for s in candidate['model']['segments'] if s['shipment']==ship and _overlap(s['start'],s['end'],start,end)]
        old=[s for s in base['model']['segments'] if s['shipment']==ship and _overlap(s['start'],s['end'],start,end)]
        unknown=[s for s in cand if s['left'] is None]
        blockers=[]
        for q in candidate['quarantine']['rows']:
            s,at=_raw_shipment_at(q['raw'])
            if s==ship and _in_window(at,start,end):blockers.append(q)
        blockers.sort(key=lambda q:q['line'])
        corrected=not unknown and not blockers
        new=_owner_totals(cand,threshold);oldt=_owner_totals(old,threshold);owners=[]
        for owner in sorted(set(new)|set(oldt)):
            minutes=new[owner][0] if owner in new else oldt[owner][0]
            if corrected:
                label=f"{owner} {fmt(minutes)}min · 超温 {fmt(oldt[owner][1])}→{fmt(new[owner][1])} · 热暴露 {fmt(oldt[owner][2])}→{fmt(new[owner][2])}"
                owners.append({'owner':owner,'minutes':fmt(minutes),'old_excess':fmt(oldt[owner][1]),'new_excess':fmt(new[owner][1]),'old_degree':fmt(oldt[owner][2]),'new_degree':fmt(new[owner][2]),'label':label})
            else:
                owners.append({'owner':owner,'minutes':fmt(minutes),'pending':True,'label':f"{owner} {fmt(minutes)}min · 待证实"})
        if corrected:
            n=sum(1 for r in candidate['contract']['rows'] if r['shipment']==ship and _in_window(r['at'],start,end))
            basis=f"窗口内{n}条有效采样覆盖{len(cand)}个责任段，无窗口内隔离证据" if cand else '修正窗口不覆盖该批号责任段，无影响'
        else:
            parts=[f"第{q['line']}行{REASONS.get(q['code'],q['code'])}已隔离" for q in blockers]
            parts+=[f"{_hhmm(s['start'])}–{_hhmm(s['end'])}缺测{fmt(Decimal(s['minutes']))}分钟未插值" for s in unknown]
            parts.append('无法证实窗口内温度，保留旧账')
            basis='；'.join(parts)
        decisions.append({'shipment':ship,'corrected':corrected,'basis':basis,'owners':owners})
    return decisions

def build_settlement(base,candidate,decisions):
    corrected={d['shipment'] for d in decisions if d['corrected']}
    rows=[]
    for ship in sorted({o['shipment'] for o in base['calculate']['owners']}|{o['shipment'] for o in candidate['calculate']['owners']}):
        source=candidate if ship in corrected else base
        for o in source['calculate']['owners']:
            if o['shipment']==ship:rows.append({**o,'source':'修正后' if ship in corrected else '旧账'})
    fields=('coverage','normal','excess','unknown','degree_minutes')
    totals={f:fmt(sum((Decimal(r[f]) for r in rows),Decimal(0))) for f in fields}
    tolerance=Decimal('0.00001')
    balanced=all(abs(Decimal(r['coverage'])-sum((Decimal(r[k]) for k in ('normal','excess','unknown')),Decimal(0)))<=tolerance for r in rows)
    balanced=balanced and abs(Decimal(totals['coverage'])-sum((Decimal(totals[k]) for k in ('normal','excess','unknown')),Decimal(0)))<=tolerance
    if not balanced:raise RuleError('UNBALANCED','修正结算不守恒，已保留旧版',409)
    return {'owners':rows,'totals':totals,'balanced':balanced}
