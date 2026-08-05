import subprocess
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class CalendarModule:
    def __init__(self):
        self.calendar_app = self._detect_calendar_app()
    
    def _detect_calendar_app(self) -> Optional[str]:
        """Detect available calendar application on Linux"""
        apps = ["khal", "calcurse", "evolution", "gnome-calendar", "ical"]
        for app in apps:
            try:
                subprocess.run(
                    ["which", app],
                    check=True,
                    capture_output=True,
                    text=True
                )
                return app
            except Exception:
                continue
        return None
    
    async def get_upcoming_events(self, days_ahead: int = 7) -> List[Dict]:
        """Get upcoming calendar events"""
        try:
            if self.calendar_app == "khal":
                return await self._get_khal_events(days_ahead)
            elif self.calendar_app == "evolution":
                return await self._get_evolution_events(days_ahead)
            elif self.calendar_app == "gnome-calendar":
                return await self._get_gnome_events(days_ahead)
            else:
                # Fallback: return mock data
                return self._get_mock_events(days_ahead)
        
        except Exception as e:
            logger.error(f"Failed to fetch calendar events: {e}")
            return []
    
    async def _get_evolution_events(self, days_ahead: int) -> List[Dict]:
        """Extract events from Evolution (GNOME calendar)"""
        try:
            # Evolution stores calendars in ~/.local/share/evolution/calendar/
            subprocess.run(
                ["evolution", "--express"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # Parse and extract events
            # This is a simplified version - real implementation would parse ICS files
            return []
        except:
            return []
    
    async def _get_gnome_events(self, days_ahead: int) -> List[Dict]:
        """Extract events from GNOME Calendar"""
        try:
            # GNOME Calendar stores data in ~/.local/share/gnome-calendar/
            # This would parse the calendar database
            return []
        except:
            return []

    async def _get_khal_events(self, days_ahead: int) -> List[Dict]:
        """Extract events from khal (Linux calendar CLI)"""
        try:
            result = subprocess.run(
                ["khal", "agenda", "today", str(days_ahead)],
                capture_output=True,
                text=True,
                timeout=8
            )

            if result.returncode != 0:
                return []

            events = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                match = re.match(
                    r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*→\s*(\d{2}:\d{2})\s*(.*)$",
                    line
                )
                if match:
                    date_part, start_part, end_part, title = match.groups()
                    start_dt = datetime.fromisoformat(f"{date_part}T{start_part}:00")
                    end_dt = datetime.fromisoformat(f"{date_part}T{end_part}:00")
                    events.append({
                        "title": title.strip() or "Untitled Event",
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat(),
                        "location": "khal",
                        "description": ""
                    })

            return events
        except Exception as e:
            logger.warning(f"Failed to parse khal agenda output: {e}")
            return []
    
    def _get_mock_events(self, days_ahead: int) -> List[Dict]:
        """Return mock events for demo"""
        events = []
        now = datetime.now()
        
        # Mock events for demonstration
        mock_data = [
            {"title": "Team Standup", "hours_offset": 2},
            {"title": "Client Meeting", "hours_offset": 4},
            {"title": "Code Review", "hours_offset": 6},
            {"title": "Project Planning", "hours_offset": 24},
        ]
        
        for event in mock_data:
            event_time = now + timedelta(hours=event["hours_offset"])
            events.append({
                "title": event["title"],
                "start": event_time.isoformat(),
                "end": (event_time + timedelta(hours=1)).isoformat(),
                "location": "Virtual",
                "description": ""
            })
        
        return events
    
    async def create_event(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        description: Optional[str] = None,
        location: Optional[str] = None
    ) -> bool:
        """Create a new calendar event"""
        try:
            # Implementation would depend on calendar app
            logger.info(f"Creating event: {title} at {start_time}")
            return True
        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            return False
    
    async def check_availability(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> bool:
        """Check if time slot is available"""
        events = await self.get_upcoming_events()
        
        for event in events:
            event_start = datetime.fromisoformat(event["start"])
            event_end = datetime.fromisoformat(event["end"])
            
            # Check for overlap
            if not (end_time <= event_start or start_time >= event_end):
                return False
        
        return True
    
    async def find_available_slot(
        self,
        duration_minutes: int = 30,
        days_ahead: int = 7
    ) -> Optional[Dict]:
        """Find next available time slot"""
        now = datetime.now()
        
        # Try to find a 30-minute slot tomorrow at 10 AM
        for day_offset in range(1, days_ahead):
            slot_time = now.replace(hour=10, minute=0) + timedelta(days=day_offset)
            
            if await self.check_availability(
                slot_time,
                slot_time + timedelta(minutes=duration_minutes)
            ):
                return {
                    "start": slot_time.isoformat(),
                    "end": (slot_time + timedelta(minutes=duration_minutes)).isoformat(),
                    "duration_minutes": duration_minutes
                }
        
        return None
