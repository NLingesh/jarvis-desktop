from fastapi import APIRouter, Request

from routes.state import performance_manager

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("/metrics")
async def get_metrics(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    return performance_manager.get_metrics()


@router.get("/health")
async def get_health(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    return performance_manager.get_system_health()
