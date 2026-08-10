from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from routes.state import model_manager, require_session_token

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/ollama")
async def list_ollama_models(request: Request):
    require_session_token(request)
    models = await model_manager.list_ollama_models()
    return {"models": models}


@router.post("/ollama/pull")
async def pull_ollama_model(request: Request):
    require_session_token(request)
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    async def generate():
        async for line in model_manager.pull_ollama_model(name):
            yield line + "\n"

    return StreamingResponse(generate(), media_type="text/plain")


@router.delete("/ollama/{name}")
async def delete_ollama_model(name: str, request: Request):
    require_session_token(request)
    success = await model_manager.delete_ollama_model(name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete model")
    return {"deleted": name}


@router.get("/ollama/{name}")
async def get_ollama_model_info(name: str, request: Request):
    require_session_token(request)
    info = await model_manager.get_ollama_model_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return info


@router.get("/storage")
async def get_storage_usage(request: Request):
    require_session_token(request)
    return await model_manager.get_storage_usage()


@router.get("/diagnostics")
async def get_model_diagnostics(request: Request):
    require_session_token(request)
    return model_manager.diagnostics()
