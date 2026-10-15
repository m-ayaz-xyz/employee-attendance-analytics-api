"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""

import calendar
import os
from datetime import date, datetime, timedelta, timezone, time
import re
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument
from decimal import Decimal, ROUND_HALF_UP
from pymongo.errors import DuplicateKeyError
from contextlib import asynccontextmanager


load_dotenv()

client = MongoClient(
    os.getenv("MONGO_URI"), serverSelectionTimeoutMS=3000
)
db = client[os.getenv("MONGO_DB")]

@asynccontextmanager
async def lifespan(app: FastAPI):
    '''Defines FastAPI lifecycle'''
    # Create Indexes in Database when application starts
    create_indexes() 
    # Allows FastApi to run startup code before the application starts serving requests
    yield

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
PRESENT_STATUSES = ["PRESENT", "WFH", "ON_DUTY"]
ALL_STATUSES = PRESENT_STATUSES + ["ABSENT", "LEAVE"]
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0", lifespan=lifespan)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def compute_late_minutes(punch_in: datetime, shift_start: str, attendance_day: str) -> int:
    h, m = parse_hhmm(shift_start)
    start = datetime.combine(validate_date(attendance_day), time(h, m), IST).astimezone(UTC)
    seconds = int((as_utc(punch_in) - start).total_seconds())
    return seconds // 60 if seconds > 600 else 0

def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = int((as_utc(punch_out) - as_utc(punch_in)).total_seconds())
    return float((Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(punch_out: datetime, emp, attendance_day: str) -> int:
    _, end = shift_datetimes(emp, attendance_day)
    minutes = int((as_utc(punch_out) - end).total_seconds()) // 60
    return minutes if minutes >= 30 else 0


# To check whether the time is in valid format HH:MM and return hours and minutes
def parse_hhmm(value: str):
    if not isinstance(value, str) or not re.fullmatch(
        r"([01]\d|2[0-3]):[0-5]\d", value
    ):
        raise HTTPException(422, "time must use HH:MM")
    h, m = map(int, value.split(":"))
    return h, m

# To validate Date in YYYY-MM-DD format
def validate_date(value: str, label="date") -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (TypeError, ValueError):
        raise HTTPException(422, f"{label} must be YYYY-MM-DD")

# To convert a datetime to UTC, adding UTC timezone if not present
def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

# To calculate the shift start and end datetimes in UTC
def shift_datetimes(emp, attendance_day: str):
    start_h, start_m = parse_hhmm(emp["shift_start"])
    end_h, end_m = parse_hhmm(emp["shift_end"])
    day = validate_date(attendance_day)
    start_local = datetime.combine(day, time(start_h, start_m), IST)
    end_day = day + timedelta(days=1) if (end_h, end_m) <= (start_h, start_m) else day
    end_local = datetime.combine(end_day, time(end_h, end_m), IST)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)

# To convert current time to UTC without microseconds
def now_utc():
    return datetime.now(UTC).replace(microsecond=0)

# To convert Python datetime to Unix epoch milliseconds
def epoch_ms(dt):
    return None if dt is None else int(as_utc(dt).timestamp() * 1000)

# to convert milliseconds timestamp to Python datetime
def from_epoch_ms(value: Optional[int]) -> datetime:
    if value is None:
        return now_utc()
    if type(value) is not int:
        raise HTTPException(422, "timestamp must be an integer epoch millisecond value")
    # Contemporary epoch milliseconds are 13 digits; reject second-based timestamps.
    if abs(value) < 100_000_000_000:
        raise HTTPException(422, "timestamp must be milliseconds, not seconds")
    try:
        return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0)
    except (ValueError, OverflowError, OSError):
        raise HTTPException(422, "invalid timestamp")

# to convert a MongoDB document to the API response format i.e. JSON
def api_record(doc):
    if not doc:
        return doc
    out = {k: v for k, v in doc.items() if k != "_id"}
    for key in ("punch_in", "punch_out"):
        if key in out:
            out[key] = epoch_ms(out[key])
    out["late_minutes"] = out.get("late_minutes", 0)
    out["overtime_minutes"] = out.get("overtime_minutes", 0)
    out["half_day"] = out.get("half_day", False)
    out["history"] = out.get("history", [])
    for entry in out["history"]:
        entry["at"] = epoch_ms(entry.get("at"))
        for change in entry.get("changes", {}).values():
            for side in ("from", "to"):
                if isinstance(change.get(side), datetime):
                    change[side] = epoch_ms(change[side])
    return out

# to determine the attendance day for a punch-in timestamp
def attendance_day_for(punch_in: datetime, emp) -> str:
    local = as_utc(punch_in).astimezone(IST)
    start = parse_hhmm(emp["shift_start"])
    end = parse_hhmm(emp["shift_end"])
    if end <= start and (local.hour, local.minute) < end:
        return (local.date() - timedelta(days=1)).isoformat()
    return local.date().isoformat()

# Used to calculate attendence value like hours, late, overtime, halfday based on punchin and punchout values. If status is not present then return None for workhours and 0 for late, overtime and halfday as False
def compute_derived(record, emp):
    status = record.get("status")
    pin, pout = record.get("punch_in"), record.get("punch_out")
    if status not in PRESENT_STATUSES:
        return {"work_hours": None, "late_minutes": 0, "overtime_minutes": 0, "half_day": False}
    late = compute_late_minutes(pin, emp["shift_start"], record["date"]) if pin else 0
    hours = compute_work_hours(pin, pout) if pin and pout else None
    overtime = compute_overtime(pout, emp, record["date"]) if pin and pout else 0
    return {"work_hours": hours, "late_minutes": late, "overtime_minutes": overtime,
            "half_day": hours is not None and hours < 4.50}

# it validates the month input and returns its starting and ending dates
def validate_month(month: str) -> tuple[date, date]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(422, "month must be YYYY-MM")
    y, m = map(int, month.split("-"))
    start = date(y, m, 1)
    return start, date(y, m, calendar.monthrange(y, m)[1])

# this helper wraps month validation and returns the start and end dates in formats useful for database queries
def month_bounds(month):
    start, end = validate_month(month)
    return start.isoformat(), end.isoformat(), start, end

# this helper builds a MongoDB aggregation pipeline that filters an employee's attendance records for a selected month and calculates monthly statistics
def monthly_pipeline(emp_code, month):
    start, end, _, _ = month_bounds(month)
    return [{"$match": {"emp_code": emp_code, "date": {"$gte": start, "$lte": end}}},
            {"$group": {"_id": None, "present_days": {"$sum": {"$cond": [{"$and": [{"$in": ["$status", PRESENT_STATUSES]}, {"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [2, 3, 4, 5, 6]]}]}, {"$cond": ["$half_day", 0.5, 1]}, 0]}},
                         "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
                         "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
                         "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
                         "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}}}}]

# this helper counts weekdays between two dates, usually from Monday to Friday
def working_days(start: date, end: date) -> int:
    if end < start:
        return 0
    pipeline = [
        {"$documents": [{"day": datetime.combine(start, time.min)}]},
        {"$densify": {"field": "day", "range": {"step": 1, "unit": "day",
                       "bounds": [datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)]}}},
        {"$match": {"$expr": {"$in": [{"$dayOfWeek": "$day"}, [2, 3, 4, 5, 6]]}}},
        {"$count": "days"}
    ]
    result = db.command("aggregate", 1, pipeline=pipeline, cursor={})
    batch = result.get("cursor", {}).get("firstBatch", [])
    return int(batch[0]["days"]) if batch else 0

# this helper rounds numerical values to a specified number of decimal places using predictable decimal rounding.
def round_num(value, places=2):
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("1" if places == 0 else "0." + "0" * places), rounding=ROUND_HALF_UP))

# this helper returns the execution plan and execution statistics for a MongoDB find query or aggregation pipeline
def explain_plan(collection, pipeline=None, query=None, sort=None, skip=0, limit=None):
    if pipeline is not None:
        return db.command("explain", {"aggregate": collection, "pipeline": pipeline, "cursor": {}}, verbosity="executionStats")
    coll = db[collection]
    return coll.find(query or {}).sort(sort or []).skip(skip).limit(limit or 20).explain("executionStats")

# Used to convert value to consistent format so that the response can be easily send in JSON format
def normalize_aggregation(value):
    if isinstance(value, datetime):
        return epoch_ms(value)
    if isinstance(value, dict):
        return {k: normalize_aggregation(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_aggregation(v) for v in value]
    return value


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"
    
class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

class RegularizeIn(BaseModel):
    status: str = ["PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"]
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str
    regularized_by: str

def create_indexes():
    db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")
    db.employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING)], name="department_joined")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date")
    db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="attendance_date_employee")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING), ("status", ASCENDING)], name="attendance_employee_date_status")
    db.attendance_logs.create_index([("date", ASCENDING), ("late_minutes", DESCENDING), ("emp_code", ASCENDING)], name="attendance_late_date")


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(503, "database unavailable")


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = now_utc()
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")
    doc["created_at"] = epoch_ms(doc["created_at"])
    return doc   


@app.get("/employees")
def list_employees(
    department: Optional[str] = None, page: int = 1, page_size: int = 20
):
    q = {"department": department} if department is not None else {}
    total = db.employees.count_documents(q)
    items = list(db.employees.find(q, {"_id": 0}).sort("emp_code", ASCENDING).skip((page - 1) * page_size).limit(page_size))
    for item in items:
        item["created_at"] = epoch_ms(item.get("created_at"))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    ts = from_epoch_ms(body.punched_at)
    day = attendance_day_for(ts, emp)
    doc = {
        "emp_code": body.emp_code, 
        "date": day, 
        "status": body.status, 
        "punch_in": ts,
        "punch_out": None, 
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"], day),
        "overtime_minutes": 0, 
        "half_day": False, 
        "history": []
        }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this date")
    return api_record(doc)


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code is not None: q["emp_code"] = emp_code
    if status is not None:
        if status not in ALL_STATUSES: raise HTTPException(422, "invalid status")
        q["status"] = status
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            validate_date(date_from, "date_from"); q["date"]["$gte"] = date_from
        if date_to:
            validate_date(date_to, "date_to"); q["date"]["$lte"] = date_to
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "date_from must not be after date_to")
    total = db.attendance_logs.count_documents(q)
    docs = list(db.attendance_logs.find(q).sort([("date", DESCENDING), ("emp_code", ASCENDING)]).skip((page - 1) * page_size).limit(page_size))
    return {"items": [api_record(d) for d in docs], "total": total, "page": page, "page_size": page_size}


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #

@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    ts = from_epoch_ms(body.punched_at)
    candidate = db.attendance_logs.find_one({"emp_code": body.emp_code, "punch_in": {"$lte": ts}}, sort=[("punch_in", DESCENDING)])
    if not candidate:
        raise HTTPException(404, "no punch-in found")
    if candidate.get("punch_out") is not None:
        raise HTTPException(409, "already punched out")
    elapsed = (ts - as_utc(candidate["punch_in"])).total_seconds()
    if elapsed <= 0 or elapsed > 24 * 3600:
        raise HTTPException(422, "punch_out must be after punch_in and within 24 hours")
    derived = compute_derived({**candidate, "punch_out": ts}, emp)
    updated = db.attendance_logs.find_one_and_update(
        {"_id": candidate["_id"], "punch_out": None},
        {"$set": {"punch_out": ts, **derived}}, return_document=ReturnDocument.AFTER)
    if not updated:
        raise HTTPException(409, "already punched out")
    return api_record(updated)


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: RegularizeIn):
    validate_date(date)
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp: raise HTTPException(404, "employee not found")
    old = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not old: raise HTTPException(404, "attendance record not found")
    req = body.model_dump(exclude_unset=True)
    status = req.get("status", old["status"])
    if status in ("ABSENT", "LEAVE") and ("punch_in" in req or "punch_out" in req):
        raise HTTPException(422, "ABSENT/LEAVE cannot include punch times")
    new = dict(old)
    if "status" in req: new["status"] = req["status"]
    for field in ("punch_in", "punch_out"):
        if field in req: new[field] = from_epoch_ms(req[field]) if req[field] is not None else None
    if new["status"] in ("ABSENT", "LEAVE"):
        new["punch_in"] = new["punch_out"] = None
    elif new.get("punch_in") is None:
        raise HTTPException(422, "presence status requires punch_in")
    elif attendance_day_for(new["punch_in"], emp) != date:
        raise HTTPException(422, "punch_in must belong to attendance date")
    if new.get("punch_out") is not None:
        if new.get("punch_in") is None:
            raise HTTPException(422, "punch_out requires punch_in")
        secs = (as_utc(new["punch_out"]) - as_utc(new["punch_in"])).total_seconds()
        if secs <= 0 or secs > 86400: raise HTTPException(422, "punch_out must be after punch_in and within 24 hours")
    derived = compute_derived(new, emp)
    new.update(derived)
    change_fields = ["status", "punch_in", "punch_out", "work_hours", "late_minutes", "overtime_minutes", "half_day"]
    changes = {}
    for field in change_fields:
        before, after = old.get(field), new.get(field)
        if field in ("late_minutes", "overtime_minutes"):
            before, after = before or 0, after or 0
        if field == "half_day": before, after = bool(before), bool(after)
        same = (as_utc(before) == as_utc(after)) if isinstance(before, datetime) and isinstance(after, datetime) else before == after
        if not same:
            changes[field] = {"from": before, "to": after}
    if not changes: raise HTTPException(422, "request makes no changes")
    entry = {"at": now_utc(), "by": body.regularized_by, "reason": body.reason, "changes": changes}
    new["history"] = old.get("history", []) + [entry]
    # Compare-and-set prevents concurrent regularizations from overwriting each other's history.
    history_filter = {"$or": [{"history": old.get("history", [])}, {"history": {"$exists": False}}]}
    result = db.attendance_logs.replace_one({"_id": old["_id"], **history_filter}, {**new, "_id": old["_id"]})
    if result.modified_count != 1: raise HTTPException(409, "record changed concurrently; retry")
    return api_record(new)


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp: raise HTTPException(404, "employee not found")
    start, end = month_bounds(month)
    result = list(db.attendance_logs.aggregate(monthly_pipeline(emp_code, month)))
    stats = result[0] if result else {}
    wd_start = max(start, validate_date(emp["joined_on"]))
    wd = working_days(wd_start, end) if wd_start <= end else 0
    present = round_num(stats.get("present_days", 0), 2)
    pct = round_num(present / wd * 100, 4) if wd else None
    return {"emp_code": emp_code, "month": month, "working_days": wd, "present_days": present,
            "leave_days": int(stats.get("leave_days", 0)), "late_count": int(stats.get("late_count", 0)),
            "total_late_minutes": int(stats.get("total_late_minutes", 0)),
            "total_overtime_minutes": int(stats.get("total_overtime_minutes", 0)), "attendance_pct": pct}

@app.get("/analytics/departments/summary")
def department_summary(month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), department: Optional[str] = None):
    start_s, end_s, start, end = month_bounds(month)
    match = {"joined_on": {"$lte": end_s}}
    if department is not None: match["department"] = department
    pipeline = [
        {"$match": match},
        {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [
            {"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$code"]}, {"$gte": ["$date", start_s]}, {"$lte": ["$date", end_s]}]}}}], "as": "logs"}},
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {"$group": {"_id": "$department", "headcount": {"$addToSet": "$emp_code"},
            "present_days": {"$sum": {"$cond": [{"$in": ["$logs.status", PRESENT_STATUSES]}, {"$cond": [{"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$logs.date"}}}, [2, 3, 4, 5, 6]]}, {"$cond": ["$logs.half_day", 0.5, 1]}, 0]}, 0]}},
            "avg_work_hours": {"$avg": {"$cond": [{"$and": [{"$in": ["$logs.status", PRESENT_STATUSES]}, {"$ne": [{"$ifNull": ["$logs.work_hours", None]}, None]}]}, "$logs.work_hours", None]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$logs.late_minutes", 0]}},
            "leave_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "LEAVE"]}, 1, 0]}},
            "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0]}}}},
        {"$project": {"_id": 0, "department": "$_id", "headcount": {"$size": "$headcount"}, "present_days": 1,
            "avg_work_hours": 1,
            "late_count": 1, "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1}},
        {"$sort": {"department": 1}}
    ]
    rows = list(db.employees.aggregate(pipeline, allowDiskUse=True))
    out = []
    for row in rows:
        row["present_days"] = round_num(row.get("present_days", 0), 2)
        row["avg_work_hours"] = round_num(row.get("avg_work_hours"), 2)
        for k in ("headcount", "late_count", "total_late_minutes", "leave_count", "on_duty_count"): row[k] = int(row.get(k, 0))
        out.append(row)
    return {"month": month, "items": out}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), limit: int = Query(10, ge=1, le=50), department: Optional[str] = None):
    start_s, end_s, _, _ = month_bounds(month)
    pipeline = [
        {"$match": {"date": {"$gte": start_s, "$lte": end_s}, "late_minutes": {"$gt": 0}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}, "late_count": {"$sum": 1}}},
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"},
    ]
    if department is not None: pipeline.append({"$match": {"employee.department": department}})
    pipeline += [
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$project": {"_id": 0, "emp_code": "$_id", "name": "$employee.name", "department": "$employee.department", "total_late_minutes": 1, "late_count": 1, "rank": 1}}
    ]
    return {"month": month, "items": list(db.attendance_logs.aggregate(pipeline, allowDiskUse=True))}

@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, from_: str = Query(..., alias="from"), to: str = Query(...)):
    start, end = validate_date(from_, "from"), validate_date(to, "to")
    if end < start:
        raise HTTPException(422, "to must be on or after from")
    if (end - start).days + 1 > 92:
        raise HTTPException(422, "range cannot exceed 92 days")
    if not db.employees.find_one({"department": department}):
        raise HTTPException(404, "department not found")

    # Generate the requested calendar range inside MongoDB, then join daily attendance and headcount.
    pipeline = [
        {"$documents": [{"dayDate": datetime.combine(start, time.min)}]},
        {"$densify": {"field": "dayDate", "range": {"step": 1, "unit": "day",
                         "bounds": [datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)]}}},
        {"$set": {"date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$dayDate"}},
                   "is_working_day": {"$in": [{"$dayOfWeek": "$dayDate"}, [2, 3, 4, 5, 6]]}}},
        {"$lookup": {"from": "attendance_logs", "let": {"day": "$date"}, "pipeline": [
            {"$match": {"$expr": {"$eq": ["$date", "$$day"]}}},
            {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "employee"}},
            {"$unwind": "$employee"}, {"$match": {"employee.department": department}},
            {"$group": {"_id": None,
                "present_count": {"$sum": {"$cond": [{"$in": ["$status", PRESENT_STATUSES]}, {"$cond": ["$half_day", 0.5, 1]}, 0]}},
                "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}}}},
            {"$project": {"_id": 0, "present_count": 1, "late_count": 1}}], "as": "daily"}},
        {"$lookup": {"from": "employees", "let": {"d": "$date"}, "pipeline": [
            {"$match": {"$expr": {"$and": [{"$eq": ["$department", department]}, {"$lte": ["$joined_on", "$$d"]}]}}},
            {"$count": "count"}], "as": "hc"}},
        {"$set": {"headcount": {"$ifNull": [{"$arrayElemAt": ["$hc.count", 0]}, 0]},
                   "present_count": {"$ifNull": [{"$arrayElemAt": ["$daily.present_count", 0]}, 0]},
                   "late_count": {"$ifNull": [{"$arrayElemAt": ["$daily.late_count", 0]}, 0]}}},
        {"$set": {"attendance_rate": {"$cond": [{"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
                                                     {"$divide": ["$present_count", "$headcount"]}, None]}}},
        {"$setWindowFields": {"sortBy": {"dayDate": 1}, "output": {
            "moving_avg_7d": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}}}},
        {"$sort": {"dayDate": 1}},
        {"$project": {"_id": 0, "date": 1, "is_working_day": 1, "headcount": 1, "present_count": 1,
                       "late_count": 1, "attendance_rate": 1, "moving_avg_7d": 1}}
    ]
    try:
        result = db.command("aggregate", 1, pipeline=pipeline, cursor={}, allowDiskUse=True)
        rows = result.get("cursor", {}).get("firstBatch", [])
    except Exception as exc:
        # Surface database pipeline errors as a clear server-side failure during development.
        raise HTTPException(500, f"trend aggregation failed: {str(exc)}")
    for row in rows:
        row["attendance_rate"] = round_num(row.get("attendance_rate"), 4)
        row["moving_avg_7d"] = round_num(row.get("moving_avg_7d"), 4)
        row["present_count"] = round_num(row.get("present_count", 0), 2)
    return {"department": department, "items": rows}


@app.get("/admin/explain/{endpoint}")
def admin_explain(endpoint: str, emp_code: Optional[str] = None, month: Optional[str] = None,
                  department: Optional[str] = None, limit: int = Query(10, ge=1, le=50),
                  date_from: Optional[str] = None, date_to: Optional[str] = None, status: Optional[str] = None,
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None):
    if endpoint == "attendance_list":
        q = {}
        if emp_code: q["emp_code"] = emp_code
        if status: q["status"] = status
        if date_from or date_to:
            q["date"] = {}
            if date_from: validate_date(date_from); q["date"]["$gte"] = date_from
            if date_to: validate_date(date_to); q["date"]["$lte"] = date_to
        exp = explain_plan("attendance_logs", query=q, sort=[("date", -1), ("emp_code", 1)], skip=(page-1)*page_size, limit=page_size)
        collection = "attendance_logs"
    elif endpoint == "employee_monthly":
        if not emp_code or not month: raise HTTPException(422, "emp_code and month are required")
        _, _, _, _ = month_bounds(month)
        exp = explain_plan("attendance_logs", pipeline=monthly_pipeline(emp_code, month)); collection = "attendance_logs"
    elif endpoint == "department_summary":
        if not month: raise HTTPException(422, "month is required")
        start_s, end_s, _, _ = month_bounds(month)
        p = [{"$match": {"joined_on": {"$lte": end_s}, **({"department": department} if department else {})}},
             {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [{"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$code"]}, {"$gte": ["$date", start_s]}, {"$lte": ["$date", end_s]}]}}}], "as": "logs"}}]
        exp = explain_plan("employees", pipeline=p); collection = "employees"
    elif endpoint == "late_leaderboard":
        if not month: raise HTTPException(422, "month is required")
        start_s, end_s, _, _ = month_bounds(month)
        p = [{"$match": {"date": {"$gte": start_s, "$lte": end_s}, "late_minutes": {"$gt": 0}}}, {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}, "late_count": {"$sum": 1}}}]
        exp = explain_plan("attendance_logs", pipeline=p); collection = "attendance_logs"
    elif endpoint == "department_trend":
        if not department or not from_ or not to: raise HTTPException(422, "department, from and to are required")
        validate_date(from_); validate_date(to)
        p = [{"$match": {"date": {"$gte": from_, "$lte": to}}}, {"$group": {"_id": "$date", "count": {"$sum": 1}}}]
        exp = explain_plan("attendance_logs", pipeline=p); collection = "attendance_logs"
    else:
        raise HTTPException(422, "unknown endpoint")
    return {"endpoint": endpoint, "collection": collection, "explain": normalize_aggregation(exp)}
