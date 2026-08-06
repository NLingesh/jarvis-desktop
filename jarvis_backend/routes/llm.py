from fastapi import APIRouter, HTTPException, Request

from routes.state import llm

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.post("/generate")
async def api_llm_generate(request: Request):
    """Generate text from configured LLM provider.

    Expected JSON body:
    - `prompt` or `message`: the user's input text
    - `conversation` (optional): list of {role, content} dicts to use as history
    - `model` (optional): override model name
    """
    body = await request.json()
    prompt = body.get("prompt") or body.get("message")
    conversation = body.get("conversation") or []
    model = body.get("model")

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    orig_model = None
    if model:
        orig_model = llm.model
        llm.model = model

    try:
        resp = await llm.get_response(
            user_message=prompt,
            conversation_history=conversation,
            context=None,
            memory_results=None,
        )
        return {"text": resp}
    finally:
        if model and orig_model is not None:
            llm.model = orig_model


@router.post("/rerank")
async def api_llm_rerank(request: Request):
    """Rerank a set of passages using the configured reranker (NVIDIA etc).

    Expected JSON body:
    - `query`: the query string
    - `passages`: list of passage strings
    - `model` (optional): override reranker model
    """
    body = await request.json()
    query = body.get("query")
    passages = body.get("passages") or []
    model = body.get("model")

    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    result = await llm.rerank(query=query, passages=passages, model=model)
    return {"result": result}
