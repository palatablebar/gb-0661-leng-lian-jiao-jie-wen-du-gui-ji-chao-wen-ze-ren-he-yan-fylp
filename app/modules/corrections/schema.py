import hashlib,json
from datetime import datetime
from decimal import Decimal
from app.errors import RuleError
from app.modules.contract.normalize import number,instant

def parse_correction(payload,calibrations):
    if not isinstance(payload,dict):raise RuleError('CORRECTION','修正内容必须为对象')
    probe=str(payload.get('probe','')).strip()
    if probe not in calibrations:raise RuleError('PROBE','探头未校准')
    if 'offset' not in payload:raise RuleError('MISSING','缺少修正偏移')
    offset=number(payload.get('offset'))
    if not Decimal('-80')<=offset<=Decimal('80'):raise RuleError('RANGE','修正偏移超出-80到80范围')
    if 'start' not in payload or 'end' not in payload:raise RuleError('MISSING','缺少修正窗口')
    start=instant(str(payload.get('start')));end=instant(str(payload.get('end')))
    if end<=start:raise RuleError('INTERVAL','修正结束必须晚于开始')
    note=str(payload.get('note','')).strip()[:200]
    canonical=json.dumps({'probe':probe,'offset':str(offset),'start':start.isoformat(),'end':end.isoformat()},sort_keys=True,ensure_ascii=False)
    return {'id':hashlib.sha256(canonical.encode()).hexdigest()[:20],'probe':probe,'offset':str(offset),'start':start.isoformat(),'end':end.isoformat(),'note':note}

def conflicts_with(a,b):
    if a['probe']!=b['probe']:return False
    return datetime.fromisoformat(a['start'])<datetime.fromisoformat(b['end']) and datetime.fromisoformat(b['start'])<datetime.fromisoformat(a['end'])
