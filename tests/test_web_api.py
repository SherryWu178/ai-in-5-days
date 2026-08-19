# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for the Singapore Corporate Canteen Web Portal & Admin API."""

from fastapi.testclient import TestClient
import pytest

from web.server import app

client = TestClient(app)


def test_health_check_endpoint():
    """Verify GET /api/health returns 200 OK."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_get_user_profile_endpoint():
    """Verify GET /api/user/profile returns stored UserProfileMemory."""
    response = client.get("/api/user/profile?user_id=sherrywuyujin@google.com")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "sherrywuyujin@google.com"
    assert data["profile"] is not None
    assert data["profile"]["preferred_canteen"] == "StrEAT"
    assert "fish" in data["profile"]["permanent_dietary_restrictions"]


def test_update_user_profile_endpoint():
    """Verify POST /api/user/profile saves and updates profile memory."""
    payload = {
        "user_id": "test_tenant@google.com",
        "preferred_canteen": "Shiok",
        "default_nutrition_goal": "Low GI",
        "permanent_dietary_restrictions": ["vegan"],
    }
    response = client.post("/api/user/profile", json=payload)
    assert response.status_code == 200
    assert response.json()["profile"]["preferred_canteen"] == "Shiok"

    get_res = client.get("/api/user/profile?user_id=test_tenant@google.com")
    assert get_res.json()["profile"]["default_nutrition_goal"] == "Low GI"


def test_admin_portal_get_and_post_menu_endpoint():
    """Verify Admin Portal GET and POST /api/admin/menu schema validation."""
    from app.tools.menu_tool import load_raw_menu, save_live_menu

    old_menu = load_raw_menu()
    try:
        get_res = client.get("/api/admin/menu")
        assert get_res.status_code == 200
        assert "facilities" in get_res.json()

        bad_post = client.post("/api/admin/menu", json={"invalid": []})
        assert bad_post.status_code == 422

        valid_payload = {
            "facilities": [
                {
                    "canteen_name": "Shiok",
                    "stations": [
                        {
                            "station_name": "Test Station",
                            "items": [
                                {
                                    "name": "Steamed Tofu Test",
                                    "ingredients": "Tofu, Soy",
                                    "dietary_tags": ["Vegan"],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        post_res = client.post("/api/admin/menu", json=valid_payload)
        assert post_res.status_code == 200
        assert post_res.json()["status"] == "success"
        assert post_res.json()["facilities_count"] == 1
    finally:
        save_live_menu(old_menu)


def test_consultation_endpoint():
    """Verify POST /api/consultation runs ADK Runner turn cleanly."""
    payload = {
        "user_id": "sherrywuyujin@google.com",
        "session_id": "test_consult_1",
        "message": "start",
    }
    res = client.post("/api/consultation", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == "sherrywuyujin@google.com"
    assert len(data["events"]) > 0
