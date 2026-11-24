"""Deterministic onboarding agent. Chat interpretation cannot waive this policy."""

GOVERNMENT = frozenset({"PAN_CARD", "AADHAAR_CARD", "PASSPORT", "DRIVING_LICENSE", "VOTER_ID"})
BANK = frozenset({"CHEQUE", "BANK_PASSBOOK"})


def workflow(person):
    from app.services.tenant_metadata import configuration, DEFAULT_CONFIG
    config = configuration(person["tenant_id"]) if person.get("tenant_id") else DEFAULT_CONFIG
    govt, bank = config["government_minimum"], config["bank_minimum"]
    documents = person.get("documents", [])
    latest = {d["kind"]: d for d in documents}
    usable = [
        d
        for d in latest.values()
        if not d["extraction"].get("is_mock") and d["extraction"].get("status") in {"success", "partial"}
    ]
    government = sorted({d["kind"] for d in usable} & set(config["government_types"]))
    banks = sorted({d["kind"] for d in usable} & set(config["bank_types"]))
    events = person.get("audit", [])

    def last(action):
        return max([-1] + [i for i, e in enumerate(events) if e["action"] == action])

    reviewed = last("fields_confirmed") > last("document_extracted")
    missing = []
    if len(government) < govt:
        missing.append(f"{govt-len(government)} more distinct government document type(s)")
    if len(banks) < bank:
        missing.append(f"{bank-len(banks)} bank document(s)")
    if not reviewed:
        missing.append("field review and confirmation")
    issues = person.get("verification", {}).get("issues", [])
    complete = not missing and not issues and bool(person.get("verification"))
    if missing:
        next_step = "Please provide " + missing[0] + "."
    elif not person.get("verification"):
        next_step = "The document minimum is met. Run the consistency audit next."
    elif issues:
        next_step = "Please resolve the consistency audit issues, then run it again."
    else:
        next_step = "The onboarding checklist is complete. You can still attach more documents."
    return {
        "stage": "complete" if complete else "in_progress",
        "government_types": government,
        "bank_types": banks,
        "minimum_government": govt,
        "minimum_bank": bank,
        "fields_reviewed": reviewed,
        "missing": missing,
        "next_step": next_step,
        "document_count": len(documents),
        "identity_verified": False,
    }
