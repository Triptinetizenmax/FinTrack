# FinTrack — Loan Management System

FinTrack is a local educational full-stack loan management app using **Python, FastAPI, PostgreSQL, HTML, CSS and JavaScript**, with a premium dark dashboard interface. It includes customer management, loan applications, approval/rejection, EMI schedules, manual demo payment records, and dashboard summaries.

> **Important:** This is a learning/demo project, not a production banking system. It does not make real credit decisions or move real money. Do not enter real customer financial information. Production use would require authentication, authorization, audit logs, security review, compliance controls, tested transaction logic, and payment-provider integration.

## Interface

- FinTrack branding with a premium dark navy interface and teal accents
- Responsive layout for desktop and smaller screens
- Existing FastAPI routes and PostgreSQL-backed workflows retained

## Features

- Dashboard metrics and recent applications
- Create and search customers
- Submit loan applications
- Filter/search applications and reject pending applications
- Approve an application with a chosen demo interest rate and tenure
- Calculate EMI and generate an amortization schedule
- Record manual demo payments against an EMI
- Track installment status and loan outstanding balance
- PostgreSQL data persistence and automatic IDs
- FastAPI JSON endpoints

## Your existing database

The app is designed to use your existing PostgreSQL database named `financial_loan_db`, including your existing `customers` and `loan_applications` records. The schema setup adds missing fields and creates the `loans`, `emi_schedule`, and `payments` tables. Back up your database before applying schema changes to important data.

## Windows / VS Code setup

1. Start PostgreSQL and make sure the `financial_loan_db` database exists.
2. Open this project folder in VS Code.
3. Activate your existing virtual environment if it is already here:
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
   Or create one:
   ```powershell
   py -3.11 -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
4. Install packages:
   ```powershell
   python -m pip install -r requirements.txt
   ```
5. Copy `.env.example` to `.env` in the project root. In VS Code Explorer, you can copy and rename the file. Set `DB_PASSWORD` to your local PostgreSQL password. **Do not share `.env` or commit it to Git.**
6. Start the app:
   ```powershell
   python -m uvicorn app:app --reload
   ```
7. Open `http://127.0.0.1:8000` in your browser. API documentation is at `http://127.0.0.1:8000/docs`.

The server initializes the schema when it starts. If startup fails, read the error in the VS Code terminal first.

## Important existing data note

The current project records include customer ID 1 (Riya) and loan applications 101–104, based on the development setup. The app does not recreate those records. The SQL synchronizes identity generators so newly created IDs follow existing IDs. If your database differs, inspect it in pgAdmin before applying changes.

## Main API routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Check DB connection |
| GET | `/api/dashboard` | Dashboard totals |
| GET/POST | `/api/customers` | List/create customers |
| GET/POST | `/api/applications` | List/create applications |
| PATCH | `/api/applications/{id}/status` | Update status (e.g. reject) |
| POST | `/api/applications/{id}/approve` | Create loan and EMI schedule |
| GET | `/api/loans` | List loans |
| GET | `/api/loans/{id}/emis` | List loan installments |
| GET | `/api/payments` | Payment history |
| POST | `/api/emis/{id}/payments` | Record a manual demo payment |
| GET | `/api/reports/summary` | Status and monthly summaries |

## Suggested test flow

1. Open the dashboard and verify it loads.
2. In Customers, confirm existing customer Riya is listed.
3. Create an application for customer 1.
4. Approve that application with a demo interest rate and tenure.
5. Open Active loans & EMIs and view the schedule.
6. Record a partial or full demo payment for an installment.
7. Open Payment history and verify the entry.

## Known limitations / next improvements

- No login or role-based permissions; only run locally while learning.
- The EMI due-date generation uses 30-day intervals as a simple demo, not calendar-month rules.
- The payment ledger is a manual demo; it is not integrated with a bank or UPI provider.
- Outstanding balance is reduced by recorded payment amount for demonstration; a production system should allocate payments to fees, interest, and principal using a reviewed accounting model.
- Add automated tests, migrations (e.g. Alembic), audit logs, CSRF protections where applicable, rate limiting, backups, and deployment hardening before production.
