from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from app.core.auth import current_user, write_access
from app.repositories.database import connection
from app.schemas.employee import (
    EmployeeInput,
    FieldsInput,
    UpdateEmployee,
    VersionInput,
)
from app.services import employees
from app.services.excel import export_excel, master_table

router = APIRouter(prefix="/api/employees", tags=["Employees"])


@router.get("", summary="List active employees across all conversations")
def listing(q: str = Query(default="", max_length=254), user=Depends(current_user)):
    return employees.list_employees(q)


@router.post("", status_code=201, summary="Create an employee explicitly through the API")
def create(body: EmployeeInput, user=Depends(write_access)):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return employees.create_employee(db, body.model_dump(), user)


@router.get("/master", summary="Get the single master worksheet as columns and rows")
def master(user=Depends(current_user)):
    return master_table(employees.list_employees())


@router.get("/export", summary="Download master_employees.xlsx")
def export(user=Depends(current_user)):
    return Response(
        export_excel(employees.list_employees()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="master_employees.xlsx"'},
    )


@router.get("/{eid}", summary="Read one employee, document fields and audit history")
def read(eid: str, user=Depends(current_user)):
    with connection() as db:
        return employees.get_employee(db, eid)


@router.patch("/{eid}", summary="Update basic employee details with a version guard")
def update(eid: str, body: UpdateEmployee, user=Depends(write_access)):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return employees.update_employee(db, eid, body.version, body.fields, user)


@router.delete("/{eid}", summary="Soft-delete an employee with a version guard")
def delete(eid: str, body: VersionInput, user=Depends(write_access)):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return employees.delete_employee(db, eid, body.version, user)


@router.post(
    "/{eid}/documents",
    summary="Classify and extract locally, then automatically prefill fields",
)
def document(
    eid: str,
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(default=""),
    user=Depends(write_access),
):
    with connection() as db:
        person = employees.get_employee(db, eid)
    try:
        content = file.file.read(request.app.state.settings.max_upload_bytes + 1)
    finally:
        file.file.close()
    result = request.app.state.pipeline.process(content, file.filename or "", document_type or None)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        updated = employees.save_document(db, eid, person["version"], result, user)
    return {"document": result, "employee": updated}


@router.put("/{eid}/fields", summary="Confirm/correct prefilled document fields")
def fields(eid: str, body: FieldsInput, user=Depends(write_access)):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return employees.confirm_fields(db, eid, body.version, body.fields, user)


@router.post("/{eid}/audit", summary="Run consistency checks; not government verification")
def audit(eid: str, body: VersionInput, user=Depends(write_access)):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return employees.verify_employee(db, eid, body.version, user)
