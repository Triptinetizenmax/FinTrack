from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import os
import math

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def db_connect():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "financial_loan_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        row_factory=dict_row,
    )


def init_db():
    schema_path = os.path.join(BASE_DIR, "sql", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = f.read()
    with db_connect() as conn:
        conn.execute(schema)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Database is initialized on startup; errors are shown in the terminal.
    init_db()
    yield

app = FastAPI(title="Financial Loan Management System", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


class CustomerCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=100)
    income: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=150)
    address: str | None = None
    date_of_birth: date | None = None

class ApplicationCreate(BaseModel):
    customer_id: int = Field(gt=0)
    loan_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    loan_purpose: str = Field(min_length=2, max_length=100)

class StatusUpdate(BaseModel):
    status: str

class ApproveLoan(BaseModel):
    annual_interest_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    tenure_months: int = Field(gt=0, le=360)

class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: str = Field(default="Manual", min_length=2, max_length=30)
    reference_note: str | None = Field(default=None, max_length=150)


def row_or_404(row, message="Record not found"):
    if row is None:
        raise HTTPException(status_code=404, detail=message)
    return row


def money(value):
    return Decimal(value).quantize(Decimal("0.01"))


def calculate_emi(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    p = float(principal)
    r = float(annual_rate) / 1200
    if months <= 0:
        raise HTTPException(status_code=400, detail="Tenure must be positive")
    if r == 0:
        return money(Decimal(str(p / months)))
    payment = p * r * (1 + r) ** months / ((1 + r) ** months - 1)
    return money(Decimal(str(payment)))


@app.get("/")
def home():
    return FileResponse(os.path.join(BASE_DIR, "templates", "index.html"))

@app.get("/api/health")
def health():
    try:
        with db_connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except psycopg.Error as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e.__class__.__name__}")

@app.get("/api/dashboard")
def dashboard():
    with db_connect() as conn:
        stats = conn.execute("""
            SELECT
              (SELECT COUNT(*) FROM customers) AS total_customers,
              (SELECT COUNT(*) FROM loan_applications) AS total_applications,
              (SELECT COUNT(*) FROM loan_applications WHERE application_status='Pending') AS pending_applications,
              (SELECT COUNT(*) FROM loan_applications WHERE application_status='Approved') AS approved_applications,
              (SELECT COUNT(*) FROM loan_applications WHERE application_status='Rejected') AS rejected_applications,
              (SELECT COALESCE(SUM(loan_amount),0) FROM loan_applications) AS requested_amount,
              (SELECT COALESCE(SUM(outstanding_balance),0) FROM loans WHERE loan_status='Active') AS active_outstanding,
              (SELECT COUNT(*) FROM emi_schedule WHERE status IN ('Due','Partial','Overdue') AND due_date < CURRENT_DATE) AS overdue_emis
        """).fetchone()
    return stats

@app.get("/api/customers")
def list_customers(search: str | None = None):
    with db_connect() as conn:
        if search:
            rows = conn.execute("""SELECT customer_id, customer_name, income, phone, email, address, date_of_birth
                FROM customers WHERE customer_name ILIKE %s OR CAST(customer_id AS TEXT) = %s ORDER BY customer_id DESC""", (f"%{search}%", search)).fetchall()
        else:
            rows = conn.execute("SELECT customer_id, customer_name, income, phone, email, address, date_of_birth FROM customers ORDER BY customer_id DESC").fetchall()
    return rows

@app.post("/api/customers", status_code=201)
def create_customer(payload: CustomerCreate):
    with db_connect() as conn:
        row = conn.execute("""INSERT INTO customers (customer_name, income, phone, email, address, date_of_birth)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING customer_id, customer_name, income, phone, email, address, date_of_birth""",
            (payload.customer_name.strip(), payload.income, payload.phone, payload.email, payload.address, payload.date_of_birth)).fetchone()
    return row

@app.get("/api/applications")
def list_applications(status: str | None = None, customer_id: int | None = None, search: str | None = None):
    sql = """SELECT a.application_id, a.customer_id, c.customer_name, a.loan_amount, a.loan_purpose,
        a.application_status, a.application_date, a.updated_at
        FROM loan_applications a JOIN customers c ON c.customer_id=a.customer_id WHERE TRUE"""
    params = []
    if status and status != "All":
        sql += " AND a.application_status=%s"
        params.append(status)
    if customer_id:
        sql += " AND a.customer_id=%s"
        params.append(customer_id)
    if search:
        sql += " AND (c.customer_name ILIKE %s OR CAST(a.application_id AS TEXT)=%s OR CAST(a.customer_id AS TEXT)=%s)"
        params.extend([f"%{search}%", search, search])
    sql += " ORDER BY a.application_id DESC"

    columns = [
        "application_id", "customer_id", "customer_name", "loan_amount",
        "loan_purpose", "application_status", "application_date", "updated_at"
    ]
    with db_connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    # Keep the API response consistent even if a connection returns tuple rows.
    return [row if isinstance(row, dict) else dict(zip(columns, row)) for row in rows]

@app.post("/api/applications", status_code=201)
def create_application(payload: ApplicationCreate):
    with db_connect() as conn:
        customer = conn.execute("SELECT customer_id FROM customers WHERE customer_id=%s", (payload.customer_id,)).fetchone()
        row_or_404(customer, "Customer ID does not exist. Create the customer first.")
        row = conn.execute("""INSERT INTO loan_applications (customer_id, loan_amount, loan_purpose)
            VALUES (%s,%s,%s)
            RETURNING application_id, customer_id, loan_amount, loan_purpose, application_status, application_date""",
            (payload.customer_id, payload.loan_amount, payload.loan_purpose.strip())).fetchone()
    return row

@app.patch("/api/applications/{application_id}/status")
def update_application_status(application_id: int, payload: StatusUpdate):
    status = payload.status.strip().title()
    if status not in {"Pending", "Approved", "Rejected"}:
        raise HTTPException(status_code=400, detail="Status must be Pending, Approved, or Rejected")
    with db_connect() as conn:
        existing = conn.execute("SELECT application_id, application_status FROM loan_applications WHERE application_id=%s", (application_id,)).fetchone()
        row_or_404(existing, "Application not found")
        if existing["application_status"] == "Approved" and status != "Approved":
            raise HTTPException(status_code=409, detail="An approved application cannot be changed here. Use loan servicing rules.")
        row = conn.execute("UPDATE loan_applications SET application_status=%s, updated_at=CURRENT_TIMESTAMP WHERE application_id=%s RETURNING application_id, application_status, updated_at", (status, application_id)).fetchone()
    return row

@app.post("/api/applications/{application_id}/approve")
def approve_application(application_id: int, payload: ApproveLoan):
    with db_connect() as conn:
        application = conn.execute("SELECT * FROM loan_applications WHERE application_id=%s FOR UPDATE", (application_id,)).fetchone()
        row_or_404(application, "Application not found")
        if application["application_status"] == "Rejected":
            raise HTTPException(status_code=409, detail="Rejected applications cannot be approved")
        existing = conn.execute("SELECT loan_id FROM loans WHERE application_id=%s", (application_id,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="A loan has already been created for this application")
        principal = money(application["loan_amount"])
        rate = payload.annual_interest_rate
        months = payload.tenure_months
        emi = calculate_emi(principal, rate, months)
        loan = conn.execute("""INSERT INTO loans (application_id, principal, annual_interest_rate, tenure_months, emi_amount, outstanding_balance)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING loan_id, application_id, principal, annual_interest_rate, tenure_months, emi_amount, outstanding_balance, disbursed_on, loan_status""",
            (application_id, principal, rate, months, emi, principal)).fetchone()
        # Build an amortization schedule; the last installment is adjusted for rounding.
        balance = principal
        due_date = date.today() + timedelta(days=30)
        for n in range(1, months + 1):
            interest = money(balance * rate / Decimal("1200"))
            principal_component = money(emi - interest)
            installment = emi
            if n == months or principal_component > balance:
                principal_component = balance
                installment = money(principal_component + interest)
            balance = max(Decimal("0.00"), money(balance - principal_component))
            due = due_date + timedelta(days=30 * (n - 1))
            conn.execute("""INSERT INTO emi_schedule (loan_id, installment_number, due_date, emi_amount, principal_component, interest_component)
                VALUES (%s,%s,%s,%s,%s,%s)""", (loan["loan_id"], n, due, installment, principal_component, interest))
        conn.execute("UPDATE loan_applications SET application_status='Approved', updated_at=CURRENT_TIMESTAMP WHERE application_id=%s", (application_id,))
    return {"message": "Application approved and EMI schedule created", "loan": loan}

@app.get("/api/loans")
def list_loans():
    with db_connect() as conn:
        return conn.execute("""SELECT l.*, a.customer_id, c.customer_name, a.loan_purpose
            FROM loans l JOIN loan_applications a ON a.application_id=l.application_id
            JOIN customers c ON c.customer_id=a.customer_id ORDER BY l.loan_id DESC""").fetchall()

@app.get("/api/loans/{loan_id}/emis")
def loan_emis(loan_id: int):
    with db_connect() as conn:
        row_or_404(conn.execute("SELECT loan_id FROM loans WHERE loan_id=%s", (loan_id,)).fetchone(), "Loan not found")
        return conn.execute("SELECT * FROM emi_schedule WHERE loan_id=%s ORDER BY installment_number", (loan_id,)).fetchall()

@app.get("/api/payments")
def list_payments():
    with db_connect() as conn:
        return conn.execute("""SELECT p.payment_id, p.emi_id, p.amount, p.payment_date, p.payment_method, p.reference_note,
            e.loan_id, e.installment_number, a.customer_id, c.customer_name
            FROM payments p JOIN emi_schedule e ON e.emi_id=p.emi_id
            JOIN loans l ON l.loan_id=e.loan_id JOIN loan_applications a ON a.application_id=l.application_id
            JOIN customers c ON c.customer_id=a.customer_id ORDER BY p.payment_id DESC""").fetchall()

@app.post("/api/emis/{emi_id}/payments", status_code=201)
def record_payment(emi_id: int, payload: PaymentCreate):
    with db_connect() as conn:
        emi = conn.execute("SELECT * FROM emi_schedule WHERE emi_id=%s FOR UPDATE", (emi_id,)).fetchone()
        row_or_404(emi, "EMI installment not found")
        remaining = money(emi["emi_amount"] - emi["amount_paid"])
        if payload.amount > remaining:
            raise HTTPException(status_code=400, detail=f"Payment exceeds remaining installment balance ({remaining})")
        payment = conn.execute("INSERT INTO payments (emi_id, amount, payment_method, reference_note) VALUES (%s,%s,%s,%s) RETURNING *",
            (emi_id, payload.amount, payload.payment_method, payload.reference_note)).fetchone()
        new_paid = money(emi["amount_paid"] + payload.amount)
        new_status = "Paid" if new_paid >= emi["emi_amount"] else "Partial"
        conn.execute("UPDATE emi_schedule SET amount_paid=%s, status=%s WHERE emi_id=%s", (new_paid, new_status, emi_id))
        loan = conn.execute("SELECT loan_id, outstanding_balance FROM loans WHERE loan_id=%s", (emi["loan_id"],)).fetchone()
        new_balance = max(Decimal("0.00"), money(loan["outstanding_balance"] - payload.amount))
        loan_status = "Closed" if new_balance == 0 else "Active"
        conn.execute("UPDATE loans SET outstanding_balance=%s, loan_status=%s WHERE loan_id=%s", (new_balance, loan_status, loan["loan_id"]))
    return {"payment": payment, "emi_status": new_status, "outstanding_balance": new_balance}

@app.get("/api/reports/summary")
def report_summary():
    with db_connect() as conn:
        by_status = conn.execute("SELECT application_status AS status, COUNT(*) AS count, COALESCE(SUM(loan_amount),0) AS amount FROM loan_applications GROUP BY application_status ORDER BY application_status").fetchall()
        monthly = conn.execute("SELECT TO_CHAR(date_trunc('month', application_date), 'YYYY-MM') AS month, COUNT(*) AS count, COALESCE(SUM(loan_amount),0) AS amount FROM loan_applications GROUP BY date_trunc('month', application_date) ORDER BY date_trunc('month', application_date) DESC LIMIT 12").fetchall()
    return {"by_status": by_status, "monthly": monthly}
