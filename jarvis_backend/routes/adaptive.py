from fastapi import APIRouter, HTTPException, Request

from routes.state import adaptive_intelligence

router = APIRouter(prefix="/api/adaptive", tags=["adaptive"])


@router.get("/behavior")
async def get_behavior_analysis(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    session_id = request.query_params.get("session_id")
    return await adaptive_intelligence.analyze_behavior(session_id)


@router.get("/insights")
async def get_insights(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    return await adaptive_intelligence.get_insights()


@router.get("/suggestions")
async def get_suggestions(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    session_id = request.query_params.get("session_id")
    suggestions = await adaptive_intelligence.get_suggestions(session_id)
    return {"suggestions": suggestions}


@router.post("/learn")
async def learn_from_interaction(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    body = await request.json()
    session_id = body.get("session_id", "")
    user_input = body.get("user_input", "")
    response = body.get("response", "")
    tool_used = body.get("tool_used")
    if not session_id or not user_input:
        raise HTTPException(status_code=400, detail="session_id and user_input are required")
    await adaptive_intelligence.learn_from_interaction(session_id, user_input, response, tool_used)
    return {"learned": True}


@router.post("/feedback")
async def record_feedback(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    body = await request.json()
    session_id = body.get("session_id", "")
    prediction = body.get("prediction", "")
    actual = body.get("actual", "")
    correct = bool(body.get("correct", False))
    if not session_id or not prediction:
        raise HTTPException(status_code=400, detail="session_id and prediction are required")
    result = await adaptive_intelligence.record_feedback(session_id, prediction, actual, correct)
    return result
