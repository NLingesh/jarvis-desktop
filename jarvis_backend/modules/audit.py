import logging

logger = logging.getLogger(__name__)


def _get_memory_manager():
    from routes.state import memory_manager

    return memory_manager


async def log_action(
    command: str, target: str, permission_used: str = "", result: str = ""
) -> None:
    try:
        memory_manager = _get_memory_manager()
        await memory_manager.log_audit(
            command=command, target=target, permission_used=permission_used, result=result
        )
    except Exception as e:
        logger.error("Audit log failed: %s", e)


async def get_recent_audit(limit: int = 200) -> list[dict]:
    memory_manager = _get_memory_manager()
    return await memory_manager.get_audit_log(limit=limit)


async def clear_audit() -> None:
    memory_manager = _get_memory_manager()
    await memory_manager.clear_audit_log()
