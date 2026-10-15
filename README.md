# Employee Attendance & Analytics API

This is a small Fastapi backend for employee records, attendance and attendance analytics. I kept the setup simple so the API can be run locally and tested through Swagger.

## Features

- Employee Management: Create and list employee records.
- Attendance Tracking: Record employee punch-in and punch-out.
- Attendance Records: Retrieve attendance records with filtering and pagination.
- Attendance Regularization: Correct attendance records while maintaining change history.
- Employee Analytics: Generate monthly attendance summaries.
- Department Analytics: View department summaries and attendance trends.
- Late Arrival Leaderboard: Rank employees based on late-arrival minutes.
- Query Performance: Inspect MongoDB query execution statistics.
- Data Consistency: Use MongoDB unique indexes to prevent duplicate employee codes and duplicate daily attendance records.

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


## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Check database connectivity |
| `POST` | `/employees` | Create an employee |
| `GET` | `/employees` | List employees |
| `POST` | `/attendance/punch-in` | Record punch-in |
| `POST` | `/attendance/punch-out` | Record punch-out |
| `GET` | `/attendance` | List attendance records |
| `PATCH` | `/attendance/{emp_code}/{date}` | Regularize attendance |
| `GET` | `/analytics/employees/{emp_code}/monthly` | Get monthly employee analytics |
| `GET` | `/analytics/departments/summary` | Get department summaries |
| `GET` | `/analytics/leaderboard/late` | Get the late-arrival leaderboard |
| `GET` | `/analytics/departments/{department}/trend` | Get department attendance trends |
| `GET` | `/admin/explain/{endpoint}` | Inspect query execution statistics |

## Database Design and Performance

MongoDB indexes support common employee and attendance queries. Unique indexes enforce employee-code uniqueness and one attendance record per employee per date.

Aggregation pipelines are used for attendance analytics, including monthly summaries, department reports, late-arrival rankings, and daily attendance trends.

## Run tests

From the project root:

```powershell
pytest -q
```

The tests in `tests/` cover helper functions that do not need a live database. Database-backed API endpoints should also be tested manually against a development database using `/docs`.

## Submitted
A REST API built using FastAPI and MongoDB to manage employee records and daily attendance. It supports punch-in, punch-out, attendance regularization, and attendance record management. It also provides monthly employee reports, department-wise summaries, late-arrival leaderboards, and department attendance trends. MongoDB indexes and aggregation pipelines help maintain data consistency and improve query performance.

## Instruction From the Kit
Read in this order:
1. `PROBLEM_STATEMENT.docx`: what you are asked to do, how it is evaluated.
2. `openapi.yaml`: the API contract and the business rules (R1 - R10).
3. `DATA_MODEL.md`: what is stored in MongoDB, with nine sample documents.
4. `app/main.py`: the starter. Put **all** your code in this one file. It must start with `uvicorn app.main:app --port 8000`.
5. `REVIEW.md`, `DECISIONS.md`: templates to fill in.

`sample_data/` holds the nine sample documents as MongoDB Extended JSON; `sample_seed.py` loads them. The grader's dataset is
much larger and contains cases they do not show.
