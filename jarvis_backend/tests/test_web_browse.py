"""Tests for WebBrowseModule — search, fetch, weather, and translate with mocked HTTP."""

import asyncio

import httpx
import pytest

from modules.web_browse import WebBrowseModule


def run(coro):
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, status_code=200, text="", json=None):
        self.status_code = status_code
        self._text = text
        self._json = json

    @property
    def text(self):
        return self._text

    def json(self):
        return self._json


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self._responses = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        return self.responses.pop(0)


@pytest.fixture
def html_results_page():
    return """<html><body>
        <div class="result">
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Example</a>
            <a class="result__snippet">A snippet about things</a>
        </div>
        <div class="result">
            <a class="result__a" href="https://other.example">Other</a>
        </div>
    </body></html>"""


def test_search_parses_html_results(monkeypatch, html_results_page):
    module = WebBrowseModule()

    class Client(FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.responses = [FakeResponse(text=html_results_page)]

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    results = run(module.search("test query"))
    assert len(results) == 2
    assert results[0]["title"] == "Example"
    assert results[0]["url"] == "https://example.com"
    assert "snippet" in results[0]


def test_search_returns_empty_on_http_error(monkeypatch):
    module = WebBrowseModule()

    class Client(FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.responses = [
                FakeResponse(status_code=202),
                FakeResponse(status_code=202),
                FakeResponse(status_code=202),
                FakeResponse(status_code=200, text="<html><body></body></html>"),
            ]

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    results = run(module.search("test"))
    assert results == []


def test_fetch_url_extracts_text(monkeypatch):
    module = WebBrowseModule()
    html = """<html><body>
        <h1>Title</h1>
        <p>Hello <b>world</b></p>
        <script>var x = 1;</script>
    </body></html>"""

    class Client(FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.responses = [FakeResponse(text=html)]

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    text = run(module.fetch_url("https://example.com"))
    assert text is not None
    assert "Hello" in text
    assert "script" not in text


def test_fetch_url_returns_none_on_error(monkeypatch):
    module = WebBrowseModule()

    class Client(FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.responses = [FakeResponse(status_code=500)]

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    assert run(module.fetch_url("https://example.com")) is None


def test_get_weather(monkeypatch):
    module = WebBrowseModule()
    geo = {"results": [{"latitude": 40.7, "longitude": -74.0}]}
    weather = {
        "current": {"temperature_2m": 21.5, "weather_code": 1, "wind_speed_10m": 5.0},
        "generationtime_ms": 12,
    }

    class Client(FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.responses = [FakeResponse(json=geo), FakeResponse(json=weather)]

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    result = run(module.get_weather("new york"))
    assert result["location"] == "new york"
    assert result["temperature"] == 21.5


def test_translate_text(monkeypatch):
    module = WebBrowseModule()

    class Client(FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.responses = [
                FakeResponse(
                    json={"responseStatus": 200, "responseData": {"translatedText": "bonjour"}}
                )
            ]

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    assert run(module.translate_text("hello", "fr")) == "bonjour"
