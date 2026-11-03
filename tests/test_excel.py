import io

from openpyxl import Workbook, load_workbook


def test_import_preview_atomic_commit_and_master(client):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["name", "email", "phone"])
    sheet.append(["Ravi", "ravi@example.com", "9876543210"])
    sheet.append(["Neha", "neha@example.com", "9876543211"])
    stream = io.BytesIO()
    workbook.save(stream)
    preview = client.post(
        "/api/imports/preview", files={"file": ("people.xlsx", stream.getvalue())}
    )
    assert preview.status_code == 200, preview.text
    assert client.get("/api/employees").json() == []
    response = client.post("/api/imports/" + preview.json()["import_id"] + "/confirm")
    assert response.status_code == 200 and response.json()["count"] == 2
    assert (
        client.post("/api/imports/" + preview.json()["import_id"] + "/confirm").status_code == 409
    )
    result = client.get("/api/employees/export")
    book = load_workbook(io.BytesIO(result.content))
    assert book.active.max_row == 3 and book.sheetnames == ["Master Employees"]
    book.close()


def test_failed_batch_rolls_back_every_row(client):
    workbook = Workbook()
    workbook.active.append(["name", "email", "phone"])
    workbook.active.append(["First", "first@example.com", "9876543210"])
    workbook.active.append(["Later", "later@example.com", "9876543211"])
    stream = io.BytesIO()
    workbook.save(stream)
    preview = client.post(
        "/api/imports/preview", files={"file": ("people.xlsx", stream.getvalue())}
    ).json()
    client.post(
        "/api/employees",
        json={"name": "Later", "email": "later@example.com", "phone": "9876543211"},
    )
    assert client.post("/api/imports/" + preview["import_id"] + "/confirm").status_code == 409
    assert [e["email"] for e in client.get("/api/employees").json()] == ["later@example.com"]


def test_master_preserves_literal_formula_text_and_strips_invalid_control_characters():
    from app.services.excel import export_excel

    record = {
        "id": "one",
        "name": "=1+1",
        "email": "a@example.com",
        "phone": "0123456789",
        "status": "draft",
        "fields": {"PAN_CARD": {"name": "A\x0cB"}},
    }
    data = export_excel([record])
    book = load_workbook(io.BytesIO(data), data_only=False)
    assert book.active["B2"].data_type == "s" and book.active["B2"].value == "=1+1"
    assert book.active["D2"].value == "0123456789"
    book.close()
