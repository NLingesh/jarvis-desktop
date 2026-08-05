import json
import os
from typing import List, Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class NotesModule:
    def __init__(self, notes_dir: str = "~/.jarvis/notes"):
        self.notes_dir = os.path.expanduser(notes_dir)
        os.makedirs(self.notes_dir, exist_ok=True)
    
    async def create_note(
        self,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
        notebook: str = "default"
    ) -> Dict:
        """Create a new note"""
        try:
            note_id = self._generate_id()
            
            note_data = {
                "id": note_id,
                "title": title,
                "content": content,
                "tags": tags or [],
                "notebook": notebook,
                "created_at": datetime.now().isoformat(),
                "modified_at": datetime.now().isoformat()
            }
            
            # Ensure notebook directory exists
            notebook_path = os.path.join(self.notes_dir, notebook)
            os.makedirs(notebook_path, exist_ok=True)
            
            # Save note
            note_file = os.path.join(notebook_path, f"{note_id}.json")
            with open(note_file, "w") as f:
                json.dump(note_data, f, indent=2)
            
            logger.info(f"Created note: {title}")
            return note_data
        
        except Exception as e:
            logger.error(f"Failed to create note: {e}")
            return {}
    
    async def get_notes(self, notebook: str = "default") -> List[Dict]:
        """Get all notes from a notebook"""
        try:
            notebook_path = os.path.join(self.notes_dir, notebook)
            
            if not os.path.exists(notebook_path):
                return []
            
            notes = []
            for filename in os.listdir(notebook_path):
                if filename.endswith(".json"):
                    file_path = os.path.join(notebook_path, filename)
                    with open(file_path, "r") as f:
                        note = json.load(f)
                        notes.append(note)
            
            # Sort by modification time (newest first)
            notes.sort(
                key=lambda x: x.get("modified_at", ""),
                reverse=True
            )
            
            return notes
        
        except Exception as e:
            logger.error(f"Failed to get notes: {e}")
            return []
    
    async def get_note(self, note_id: str, notebook: str = "default") -> Optional[Dict]:
        """Get a specific note"""
        try:
            note_file = os.path.join(
                self.notes_dir,
                notebook,
                f"{note_id}.json"
            )
            
            if not os.path.exists(note_file):
                return None
            
            with open(note_file, "r") as f:
                return json.load(f)
        
        except Exception as e:
            logger.error(f"Failed to get note {note_id}: {e}")
            return None
    
    async def update_note(
        self,
        note_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notebook: str = "default"
    ) -> bool:
        """Update an existing note"""
        try:
            note = await self.get_note(note_id, notebook)
            if not note:
                return False
            
            if title:
                note["title"] = title
            if content:
                note["content"] = content
            if tags is not None:
                note["tags"] = tags
            
            note["modified_at"] = datetime.now().isoformat()
            
            note_file = os.path.join(
                self.notes_dir,
                notebook,
                f"{note_id}.json"
            )
            
            with open(note_file, "w") as f:
                json.dump(note, f, indent=2)
            
            logger.info(f"Updated note: {note_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to update note: {e}")
            return False
    
    async def delete_note(self, note_id: str, notebook: str = "default") -> bool:
        """Delete a note"""
        try:
            note_file = os.path.join(
                self.notes_dir,
                notebook,
                f"{note_id}.json"
            )
            
            if os.path.exists(note_file):
                os.remove(note_file)
                logger.info(f"Deleted note: {note_id}")
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Failed to delete note: {e}")
            return False
    
    async def search_notes(
        self,
        query: str,
        notebook: str = "default"
    ) -> List[Dict]:
        """Search notes by title or content"""
        try:
            notes = await self.get_notes(notebook)
            query_lower = query.lower()
            
            results = [
                note for note in notes
                if query_lower in note.get("title", "").lower()
                or query_lower in note.get("content", "").lower()
                or any(query_lower in tag.lower() for tag in note.get("tags", []))
            ]
            
            return results
        
        except Exception as e:
            logger.error(f"Failed to search notes: {e}")
            return []
    
    def _generate_id(self) -> str:
        """Generate unique note ID"""
        import uuid
        return str(uuid.uuid4())[:8]
