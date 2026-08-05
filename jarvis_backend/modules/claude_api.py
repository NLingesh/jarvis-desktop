import anthropic
import json
import os
from typing import List, Dict, Optional

class ClaudeAPI:
    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")  # Fast model for voice responsiveness
    
    async def get_response(
        self,
        user_message: str,
        conversation_history: List[Dict],
        context: Optional[Dict] = None,
        memory_results: Optional[List[Dict]] = None,
    ) -> str:
        """Get response from Claude with context awareness"""
        
        system_prompt = self._build_system_prompt(context, memory_results)
        
        messages = conversation_history + [
            {"role": "user", "content": user_message}
        ]
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=system_prompt,
                messages=messages
            )
            
            return response.content[0].text
        
        except Exception as e:
            return f"I encountered an error: {str(e)}"
    
    def _build_system_prompt(self, context: Optional[Dict], memory_results: Optional[List[Dict]] = None) -> str:
        """Build dynamic system prompt based on available context"""
        
        base_prompt = """You are JARVIS, a voice-first AI assistant for Linux. 
You respond concisely and naturally, as if speaking out loud. 
Keep responses brief (1-2 sentences max) for voice clarity.
Be helpful, accurate, and proactive.
Format responses for speech - avoid special characters and markdown.

Current capabilities:
- Calendar management and scheduling
- Email reading and management  
- Note creation and organization
- Web browsing and research
- System information and status
- Task planning and execution

When the user asks you to do something:
1. Clearly state what you're doing
2. Execute the action if possible
3. Confirm completion with the result"""
        
        if not context:
            return base_prompt
        
        # Add context information
        context_parts = [base_prompt]
        
        if context.get("calendar"):
            context_parts.append(f"\n\nUpcoming events: {json.dumps(context['calendar'])}")
        
        if context.get("emails"):
            context_parts.append(f"\n\nRecent emails: {json.dumps(context['emails'][:3])}")
        
        if context.get("web_results"):
            context_parts.append(f"\n\nWeb results: {json.dumps(context['web_results'][:3])}")
        
        if context.get("system_info"):
            context_parts.append(f"\n\nSystem status: {json.dumps(context['system_info'])}")
        
        if memory_results:
            memory_text = "\n".join(
                f"- [{r.get('role', 'user')}] {r.get('content', '')}"
                for r in memory_results[:5]
            )
            context_parts.append(f"\n\nRelevant past conversations:\n{memory_text}")
        
        return "\n".join(context_parts)
    
    async def stream_response(
        self,
        user_message: str,
        conversation_history: List[Dict],
        context: Optional[Dict] = None,
        memory_results: Optional[List[Dict]] = None,
        on_text_chunk: Optional[callable] = None,
    ):
        """Stream response from Claude for real-time feedback"""
        
        system_prompt = self._build_system_prompt(context, memory_results)
        messages = conversation_history + [
            {"role": "user", "content": user_message}
        ]
        
        with self.client.messages.stream(
            model=self.model,
            max_tokens=500,
            system=system_prompt,
            messages=messages
        ) as stream:
            for text in stream.text_stream:
                if text:
                    if on_text_chunk:
                        on_text_chunk(text)
                    yield text
