from __future__ import annotations

import json
import threading
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import DailyClosing, Expense, Order, OrderItem, Product
from app.services.pos_service import BUSINESS_ZONE, money, sales_summary

OPEN_TIME = time(10, 0)
CLOSE_TIME = time(2, 0)
_worker_started = False


def local_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(BUSINESS_ZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(BUSINESS_ZONE)


def business_date_for(now: datetime | None = None) -> date:
    current = local_now(now)
    return current.date() - timedelta(days=1) if current.time() < CLOSE_TIME else current.date()


def business_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, OPEN_TIME, BUSINESS_ZONE)
    end = datetime.combine(day + timedelta(days=1), CLOSE_TIME, BUSINESS_ZONE)
    return (start.astimezone(timezone.utc).replace(tzinfo=None),
            end.astimezone(timezone.utc).replace(tzinfo=None))


def business_status(now: datetime | None = None) -> dict:
    current = local_now(now)
    opened = current.time() >= OPEN_TIME or current.time() < CLOSE_TIME
    day = business_date_for(current)
    if opened:
        _, closes_utc = business_day_bounds(day)
        next_change = closes_utc.replace(tzinfo=timezone.utc).astimezone(BUSINESS_ZONE)
    else:
        next_change = datetime.combine(current.date(), OPEN_TIME, BUSINESS_ZONE)
    return {
        "open": opened,
        "business_date": day.isoformat(),
        "opens_at": "10:00 AM",
        "closes_at": "2:00 AM",
        "next_change_at": next_change.isoformat(),
        "message": ("Orders are open until 2:00 AM." if opened else
                    "Daily closing is complete. Orders reopen at 10:00 AM."),
    }


def generate_daily_closing(session: Session, day: date) -> DailyClosing:
    existing = session.scalar(select(DailyClosing).where(DailyClosing.closing_date == day))
    start, end = business_day_bounds(day)
    summary = sales_summary(session, start, end)
    expenses = sum((Decimal(str(value or 0)) for value in session.scalars(
        select(Expense.amount).where(Expense.expense_date == day))), Decimal("0"))
    status_rows = session.execute(
        select(Order.approval_status, func.count(Order.id))
        .where(Order.created_at >= start, Order.created_at < end)
        .group_by(Order.approval_status)
    ).all()
    top_items = session.execute(
        select(Product.name, func.sum(OrderItem.quantity))
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.created_at >= start, Order.created_at < end, Order.status != "cancelled")
        .group_by(Product.name).order_by(func.sum(OrderItem.quantity).desc()).limit(10)
    ).all()
    report = {
        "business_date": day.isoformat(), "opened_at": f"{day.isoformat()} 10:00 AM",
        "closed_at": f"{(day + timedelta(days=1)).isoformat()} 2:00 AM",
        "orders": summary["orders"], "gross_sales": float(summary["gross_sales"]),
        "net_sales": float(summary["net_sales"]), "cashback": float(summary["cashback"]),
        "cash": float(summary["cash"]), "card": float(summary["card"]),
        "online": float(summary["online"]), "expenses": float(money(expenses)),
        "net_after_expenses": float(money(summary["net_sales"] - expenses)),
        "awaiting": summary["awaiting"], "pending_cashback": summary["pending_cashback"],
        "approval_statuses": {status or "unknown": count for status, count in status_rows},
        "top_items": [{"name": name, "quantity": int(quantity or 0)} for name, quantity in top_items],
    }
    closing = existing or DailyClosing(closing_date=day)
    closing.total_sales = summary["net_sales"]
    closing.total_expenses = money(expenses)
    closing.report_json = json.dumps(report)
    closing.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if not existing:
        session.add(closing)
    session.commit()
    session.refresh(closing)
    return closing


def ensure_latest_closing(now: datetime | None = None) -> DailyClosing | None:
    current = local_now(now)
    # Before 2 AM, yesterday's trading day is still open; the most recently
    # completed period is therefore the day before yesterday.
    days_back = 2 if current.time() < CLOSE_TIME else 1
    latest_closed_day = current.date() - timedelta(days=days_back)
    with SessionLocal() as session:
        return generate_daily_closing(session, latest_closed_day)


def serialize_closing(closing: DailyClosing) -> dict:
    report = json.loads(closing.report_json or "{}")
    report.update({"id": closing.id, "business_date": closing.closing_date.isoformat(),
                   "closed_at_timestamp": closing.closed_at.isoformat() if closing.closed_at else None})
    return report


def start_closing_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    def work():
        while True:
            try:
                ensure_latest_closing()
            except Exception:
                pass
            threading.Event().wait(60)
    threading.Thread(target=work, name="daily-closing-worker", daemon=True).start()
