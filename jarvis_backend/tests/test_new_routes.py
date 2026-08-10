"""Integration tests for new API routes: tasks, automation, adaptive, proactive, security, performance."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main as main_app


@pytest.fixture
def client():
    with TestClient(main_app.app) as c:
        yield c


def test_tasks_crud(client):
    resp = client.post("/api/tasks/", json={"title": "Test task", "type": "task"})
    assert resp.status_code == 200
    task = resp.json()
    assert task["title"] == "Test task"
    assert task["status"] == "pending"

    task_id = task["id"]
    got = client.get(f"/api/tasks/{task_id}")
    assert got.status_code == 200
    assert got.json()["id"] == task_id

    patch = client.patch(f"/api/tasks/{task_id}", json={"status": "completed"})
    assert patch.status_code == 200
    assert patch.json()["status"] == "completed"

    complete = client.post(f"/api/tasks/{task_id}/complete")
    assert complete.status_code == 200

    delete = client.delete(f"/api/tasks/{task_id}")
    assert delete.status_code == 200
    assert delete.json()["deleted"] is True


def test_tasks_list_filter(client):
    client.post("/api/tasks/", json={"title": "Task A", "type": "task"})
    client.post("/api/tasks/", json={"title": "Reminder B", "type": "reminder"})
    resp = client.get("/api/tasks/?type=reminder")
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()["tasks"]]
    assert "Reminder B" in titles


def test_automation_workflows(client):
    resp = client.post(
        "/api/automation/workflows",
        json={
            "name": "Test Workflow",
            "trigger": {"condition": "always"},
            "actions": [{"type": "notify", "message": "Hello"}],
        },
    )
    assert resp.status_code == 200
    workflow = resp.json()
    assert workflow["name"] == "Test Workflow"

    wf_id = workflow["id"]
    execute = client.post(f"/api/automation/workflows/{wf_id}/execute", json={"context": {}})
    assert execute.status_code == 200

    delete = client.delete(f"/api/automation/workflows/{wf_id}")
    assert delete.status_code == 200
    assert delete.json()["deleted"] is True


def test_adaptive_behavior(client):
    resp = client.get("/api/adaptive/behavior")
    assert resp.status_code == 200
    data = resp.json()
    assert "frequent_commands" in data
    assert "suggested_actions" in data


def test_adaptive_insights(client):
    resp = client.get("/api/adaptive/insights")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_patterns" in data
    assert "feedback_accuracy" in data


def test_adaptive_learn(client):
    resp = client.post(
        "/api/adaptive/learn",
        json={"session_id": "test", "user_input": "hello", "response": "hi", "tool_used": "chat"},
    )
    assert resp.status_code == 200
    assert resp.json()["learned"] is True


def test_adaptive_feedback(client):
    resp = client.post(
        "/api/adaptive/feedback",
        json={
            "session_id": "test",
            "prediction": "open browser",
            "actual": "opened",
            "correct": True,
        },
    )
    assert resp.status_code == 200


def test_proactive_suggestions(client):
    resp = client.get("/api/proactive/suggestions")
    assert resp.status_code == 200
    assert "suggestions" in resp.json()


def test_proactive_notifications(client):
    resp = client.post(
        "/api/proactive/notifications",
        json={"title": "Test", "body": "Notification body"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test"
    assert "id" in data


def test_security_status(client):
    resp = client.get("/api/security/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "encryption_enabled" in data
    assert "auth_enabled" in data


def test_security_privacy(client):
    resp = client.get("/api/security/privacy")
    assert resp.status_code == 200
    data = resp.json()
    assert "data_collection" in data
    assert "encryption" in data


def test_security_export(client):
    resp = client.get("/api/security/export")
    assert resp.status_code == 200
    data = resp.json()
    assert "exported_at" in data


def test_security_delete_requires_confirm(client):
    resp = client.delete("/api/security/data")
    assert resp.status_code == 400
    assert "confirm" in resp.json()["detail"]


def test_performance_metrics(client):
    resp = client.get("/api/performance/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime_seconds" in data
    assert "requests_per_minute" in data


def test_performance_health(client):
    resp = client.get("/api/performance/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "checks" in data
