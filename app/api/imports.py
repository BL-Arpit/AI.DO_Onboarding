import json
import secrets
import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.core.auth import write_access
from app.repositories.database import connection
from app.services.employees import create_employee
from app.services.excel import parse_excel

router = APIRouter(prefix="/api/imports", tags=["Excel imports"])


def create_preview(content, filename, user):
    try:
        preview = parse_excel(content, filename)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    with connection() as db:
        accepted = []
        for row in preview["accepted"]:
            if db.execute(
                "SELECT 1 FROM employees WHERE email=?", (row["person"]["email"],)
            ).fetchone():
                preview["rejected"].append(
                    {
                        "row": row["row"],
                        "name": row["person"]["name"],
                        "issues": ["Employee email already exists."],
                    }
                )
            else:
                accepted.append(row)
        preview["accepted"] = accepted
        iid = secrets.token_hex(16)
        db.execute("DELETE FROM imports WHERE expires<?", (time.time(),))
        db.execute(
            "INSERT INTO imports VALUES(?,?,?,?,0)",
            (iid, user["id"], json.dumps(preview), time.time() + 600),
        )
    return {
        "reply": "Review the Excel rows and confirm the import.",
        "action": "import",
        "import_id": iid,
        "preview": preview,
    }


@router.post("/preview", summary="Preview raw XLS/XLSX rows without saving employees")
def preview(request: Request, file: UploadFile = File(...), user=Depends(write_access)):
    try:
        content = file.file.read(request.app.state.settings.max_upload_bytes + 1)
    finally:
        file.file.close()
    if len(content) > request.app.state.settings.max_upload_bytes:
        raise HTTPException(413, "Workbook exceeds upload limit.")
    return create_preview(content, file.filename or "", user)


@router.post("/{iid}/confirm", summary="Commit one preview atomically; replay is rejected")
def confirm(iid: str, user=Depends(write_access)):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM imports WHERE id=? AND user_id=?", (iid, user["id"])
        ).fetchone()
        if not row or row["confirmed"] or row["expires"] < time.time():
            raise HTTPException(409, "Import preview expired or already confirmed.")
        data = json.loads(row["preview"])
        if not data["accepted"]:
            raise HTTPException(422, "No valid employee rows to import.")
        added = [create_employee(db, item["person"], user) for item in data["accepted"]]
        db.execute("UPDATE imports SET confirmed=1 WHERE id=?", (iid,))
    return {
        "reply": f"Imported {len(added)} employees.",
        "action": "imported",
        "count": len(added),
        "employees": added,
    }
