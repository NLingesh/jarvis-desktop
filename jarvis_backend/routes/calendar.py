from fastapi import APIRouter

from routes.state import calendar

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/events")
async def get_calendar_events():
    """Get upcoming calendar events"""
    return await calendar.get_upcoming_events()
