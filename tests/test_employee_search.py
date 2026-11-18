import json

import httpx
import pytest
from fastapi import HTTPException

from app.repositories.database import connection
from app.services import employee_search, employees


def test_directory_rechecks_index_results_and_requires_staff(client, monkeypatch):
    owner = client.get("/api/auth/session").json()["user"]
    with connection() as db:
        arpit = employees.create_employee(
            db, {"name": "Arpit Sahu", "email": "arpit@example.com", "phone": "1231231231"}, owner
        )

    calls = []
    endpoint = "/collections/test"
    point = employee_search._point(arpit)

    def respond(request):
        calls.append(request)
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"result": {"points": [
                {"payload": {"employee_id": arpit["id"], "signature": "stale"}},
                {"payload": point["payload"]},
                {"payload": point["payload"]},
            ]}})
        return httpx.Response(200, json={})

    def qdrant():
        return httpx.Client(base_url="https://qdrant.invalid", transport=httpx.MockTransport(respond)), endpoint

    monkeypatch.setattr(employee_search, "_client", qdrant)
    assert employee_search.index_employee(arpit["id"])
    sent = json.loads(calls[-1].content)
    assert "arpit@example.com" not in str(sent)
    assert "1231231231" not in str(sent)
    assert [x["id"] for x in employee_search.search_employees("pending review", owner)] == [arpit["id"]]
    with pytest.raises(HTTPException) as exc:
        employee_search.search_employees("Arpit", {**owner, "role": "employee"})
    assert exc.value.status_code == 403
    with connection() as db:
        employees.delete_employee(db, arpit["id"], arpit["version"], owner)
    assert employee_search.search_employees("pending review", owner) == []
