import httpx
import logging
import re
import asyncio
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class WebBrowseModule:
    def __init__(self):
        self.timeout = 12

    async def search(self, query: str, num_results: int = 5) -> List[Dict]:
        """Search the web for information (DuckDuckGo HTML results)."""
        # DuckDuckGo occasionally answers with a bot-challenge page (HTTP 202);
        # retry with a small delay before giving up.
        for attempt in range(3):
            try:
                results = await self._duckduckgo_html(query, num_results)
                if results:
                    return results
            except Exception as e:
                logger.warning(f"DuckDuckGo HTML search failed: {e}")
            await asyncio.sleep(0.5 * (attempt + 1))

        try:
            results = await self._duckduckgo_lite(query, num_results)
            if results:
                return results
        except Exception as e:
            logger.warning(f"DuckDuckGo Lite search failed: {e}")
        return []

    async def _duckduckgo_html(self, query: str, num_results: int = 5) -> List[Dict]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
        ) as client:
            response = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
            )
            if response.status_code != 200:
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            results = []
            for result in soup.select("div.result")[:num_results]:
                link = result.select_one("a.result__a")
                snippet = result.select_one("a.result__snippet")
                if not link:
                    continue
                url = link.get("href", "")
                if url.startswith("//duckduckgo.com/l/"):
                    m = re.search(r"uddg=([^&]+)", url)
                    if m:
                        from urllib.parse import unquote
                        url = unquote(m.group(1))
                title = link.get_text(strip=True)
                results.append({
                    "title": title or query,
                    "snippet": snippet.get_text(strip=True) if snippet else "",
                    "url": url,
                    "source": "DuckDuckGo",
                })
            return results

    async def _duckduckgo_lite(self, query: str, num_results: int = 5) -> List[Dict]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
        ) as client:
            response = await client.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
            )
            if response.status_code != 200:
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            results = []
            links = soup.select("a.result-link")
            snips = soup.select("td.result-snippet")
            for i, link in enumerate(links[:num_results]):
                url = link.get("href", "")
                snippet = snips[i].get_text(strip=True) if i < len(snips) else ""
                results.append({
                    "title": link.get_text(strip=True) or query,
                    "snippet": snippet,
                    "url": url,
                    "source": "DuckDuckGo Lite",
                })
            return results

    async def fetch_url(self, url: str) -> Optional[str]:
        """Fetch and extract text content from a URL"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=self.timeout)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    
                    # Get text
                    text = soup.get_text()
                    
                    # Clean up whitespace
                    lines = (line.strip() for line in text.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    text = " ".join(chunk for chunk in chunks if chunk)
                    
                    return text[:2000]  # Return first 2000 chars
        
        except Exception as e:
            logger.error(f"Failed to fetch URL {url}: {e}")
        
        return None
    
    async def get_weather(self, location: str) -> Optional[Dict]:
        """Get weather information for a location"""
        try:
            # Using Open-Meteo API (no API key required)
            async with httpx.AsyncClient() as client:
                # First, get coordinates for location
                geo_response = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": location, "count": 1, "language": "en"},
                    timeout=self.timeout
                )
                
                if geo_response.status_code == 200:
                    geo_data = geo_response.json()
                    if geo_data.get("results"):
                        result = geo_data["results"][0]
                        latitude = result.get("latitude")
                        longitude = result.get("longitude")
                        
                        # Get weather
                        weather_response = await client.get(
                            "https://api.open-meteo.com/v1/forecast",
                            params={
                                "latitude": latitude,
                                "longitude": longitude,
                                "current": "temperature_2m,weather_code,wind_speed_10m"
                            },
                            timeout=self.timeout
                        )
                        
                        if weather_response.status_code == 200:
                            weather_data = weather_response.json()
                            current = weather_data.get("current", {})
                            
                            return {
                                "location": location,
                                "temperature": current.get("temperature_2m"),
                                "weather_code": current.get("weather_code"),
                                "wind_speed": current.get("wind_speed_10m"),
                                "units": weather_data.get("generationtime_ms")
                            }
        
        except Exception as e:
            logger.error(f"Failed to get weather: {e}")
        
        return None
    
    async def get_news(self, topic: str = "general", limit: int = 5) -> List[Dict]:
        """Get news articles about a topic"""
        try:
            # This would require a news API key in production
            # For now, returning mock data
            results = []
            
            # In production, use NewsAPI.org or similar
            # news_api_url = f"https://newsapi.org/v2/everything?q={topic}&sortBy=publishedAt"
            
            logger.info(f"Getting news for: {topic}")
            return results
        
        except Exception as e:
            logger.error(f"Failed to get news: {e}")
            return []
    
    async def translate_text(self, text: str, target_language: str) -> Optional[str]:
        """Translate text to target language"""
        try:
            # Using MyMemory Translation API (free, no key required)
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.mymemory.translated.net/get",
                    params={
                        "q": text,
                        "langpair": f"en|{target_language}"
                    },
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("responseStatus") == 200:
                        return data.get("responseData", {}).get("translatedText")
        
        except Exception as e:
            logger.error(f"Translation failed: {e}")
        
        return None
