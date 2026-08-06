"""Explicit OpenAPI schema definitions for the JARVIS backend.

FastAPI auto-generates ``/openapi.json`` and ``/docs`` from route
declarations, but this module provides richer, human-authored descriptions
for every public endpoint so that the Swagger UI is self-documenting.
"""

from fastapi import FastAPI

from routes.state import SETTING_KEY_NAMES


def apply_openapi_schema(app: FastAPI) -> None:
    """Post-process the auto-generated OpenAPI schema with descriptions."""
    if app.openapi_schema:
        return

    from fastapi.openapi.utils import get_openapi

    openapi_schema = get_openapi(
        title="JARVIS Voice Assistant API",
        description=(
            "REST API for the JARVIS voice assistant backend. "
            "All endpoints under /api (except /api/auth/register and "
            "/api/auth/login) require an ``Authorization: Bearer <token>`` "
            "header obtained from /api/auth/login."
        ),
        version="1.0.0",
        routes=app.routes,
    )

    # Enhance system endpoints
    if "/api/system/execute" in openapi_schema["paths"]:
        execute = openapi_schema["paths"]["/api/system/execute"]["post"]
        execute["summary"] = "Execute a safe, allowlisted system command"
        execute["description"] = (
            "Runs a system command drawn from a strict allowlist "
            "(echo, cat, ls, pwd, whoami, date, uname). "
            "Shell metacharacters are rejected. Requires a Bearer token."
        )
        execute["security"] = [{"BearerAuth": []}]

    # Enhance settings endpoints
    if "/api/settings/keys" in openapi_schema["paths"]:
        get_keys = openapi_schema["paths"]["/api/settings/keys"]["get"]
        get_keys["summary"] = "List masked API key / mail credential previews"
        get_keys["description"] = (
            "Returns masked previews (e.g. ``sk-ant-****1234``) for keys "
            "configured in the .env file. Never returns full key values. "
            f"Managed keys: {', '.join(SETTING_KEY_NAMES)}."
        )
        get_keys["security"] = [{"BearerAuth": []}]

        post_keys = openapi_schema["paths"]["/api/settings/keys"]["post"]
        post_keys["summary"] = "Persist API keys and trigger backend restart"
        post_keys["description"] = (
            "Writes the supplied key=value pairs to the .env file and "
            "schedules a backend restart to reload configuration."
        )
        post_keys["security"] = [{"BearerAuth": []}]

    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "token",
            "description": "Opaque session token returned by POST /api/auth/login.",
        }
    }

    app.openapi_schema = openapi_schema


def custom_openapi(app: FastAPI):
    """Return the (possibly cached) OpenAPI schema for the app."""
    if app.openapi_schema:
        return app.openapi_schema
    apply_openapi_schema(app)
    return app.openapi_schema
