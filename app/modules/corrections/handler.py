from fastapi import APIRouter,Body
from app import store
from app.errors import RuleError
router=APIRouter()

@router.get('/api/corrections')
def current():
    bundle=store.latest()
    if not bundle or 'correction' not in bundle:raise RuleError('NO_CORRECTION','当前批次没有修正记录',404)
    return bundle['correction']

@router.post('/api/corrections')
def apply(payload:dict=Body(...)):
    from app.modules.corrections.service import apply_correction
    return apply_correction(payload)
