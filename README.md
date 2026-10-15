# Employee Attendance & Analytics API

This is a small Fastapi backend for employee records, attendance and attendance analytics. I kept the setup simple so the API can be run locally and tested through Swagger.

## Features

- Create and list employees
- Punch in and punch out
- List attendance with filters and pagination
- Regularize an attendance record and keep a change history
- Monthly employee attendance summary
- Department summary, late-arrival leaderboard and department trend
- MongoDB query execution-plan endpoint
- MongoDB indexes created when the application starts

## Local setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set MONGO_URI / MONGO_DB (local docker: docker run -p 27017:27017 mongo:7)
pytest -q  #To run test Case
python sample_seed.py
uvicorn app.main:app --port 8000 --reload
```
MongoDB **6.0 or newer** is required (the grader uses 7.0). MongoDB Atlas free tier (M0) works.

## Quick manual test

Use Swagger UI (`/docs`) and try the APIs in this order:

1. `POST /employees`
2. `GET /employees`
3. `POST /attendance/punch-in`
4. `POST /attendance/punch-out`
5. `GET /attendance`
6. Try the analytics APIs with a month in `YYYY-MM` format, for example `2026-10`.

Example employee request:

```json
{
  "emp_code": "EMP9001",
  "name": "Rahul Sharma",
  "email": "rahul@example.com",
  "department": "Engineering",
  "shift_start": "09:30",
  "shift_end": "18:30",
  "joined_on": "2026-01-15"
}
```

Example punch-in request:

```json
{
  "emp_code": "EMP9001",
  "status": "PRESENT"
}
```

`punched_at` is optional. If supplied, it must be an integer Unix timestamp in milliseconds. Use a test employee code when testing and clean up test data from your development database if needed.

For attendance regularization, check the request schema in Swagger. The request includes a reason and the name/identifier of the person making the change (`regularized_by`).

## Run tests

From the project root:

```powershell
pytest -q
```

The tests in `tests/` cover helper functions that do not need a live database. Database-backed API endpoints should also be tested manually against a development database using `/docs`.

## Submit
A public Git repository with `app/main.py`, `requirements.txt`, `REVIEW.md`, `DECISIONS.md` and a short `README.md`.
No `.env`, no secrets, no Dockerfile.

## Instruction From the Kit
Read in this order:
1. `PROBLEM_STATEMENT.docx`: what you are asked to do, how it is evaluated.
2. `openapi.yaml`: the API contract and the business rules (R1 - R10).
3. `DATA_MODEL.md`: what is stored in MongoDB, with nine sample documents.
4. `app/main.py`: the starter. Put **all** your code in this one file. It must start with `uvicorn app.main:app --port 8000`.
5. `REVIEW.md`, `DECISIONS.md`: templates to fill in.

`sample_data/` holds the nine sample documents as MongoDB Extended JSON; `sample_seed.py` loads them. The grader's dataset is
much larger and contains cases they do not show.
