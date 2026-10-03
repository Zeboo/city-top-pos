from __future__ import annotations

import csv
import hmac
import io
import os
import re
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal
from fastapi.staticfiles import StaticFiles

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from starlette.middleware.sessions import SessionMiddleware

from app.database import SessionLocal, init_db
from app.models import (Category, Customer, DailyClosing, Deal, InventoryItem, InventoryMovement, InventoryRecipe,
                        Order, OrderItem, Product, ProductVariant, User)
from app.services import (
    authenticate,
    business_period_bounds,
    checkout,
    order_net_total,
    password_hash,
    sales_summary,
    seed_demo_menu,
    seed_users,
)
from app.services.sync_service import (queue_order, save_sync_settings, start_sync_worker,
                                       sync_pending_orders, sync_settings)
from app.services.business_service import (business_status, ensure_latest_closing,
                                            serialize_closing, start_closing_worker)
from app.services.pos_service import BUSINESS_ZONE

WEB_ROOT = Path(__file__).resolve().parent / "web"
app = FastAPI(title="Top City POS", version="1.0.0")
app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
app.mount("/resources", StaticFiles(directory=WEB_ROOT.parent / "resources"), name="resources")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET") or secrets.token_urlsafe(48), max_age=60 * 60 * 24 * 7)


class LoginRequest(BaseModel):
    username: str
    password: str
    role: str = "cashier"


class CartLine(BaseModel):
    product_id: int | None = None
    variant_id: int | None = None
    deal_id: int | None = None
    quantity: int = Field(gt=0, le=100)


class CheckoutRequest(BaseModel):
    lines: list[CartLine] = Field(min_length=1)
    order_type: Literal["takeaway", "delivery"] = "takeaway"
    payment_method: Literal["cash", "card", "online payment"] = "cash"
    discount: Decimal = Field(default=Decimal("0"), ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_address: str | None = None
    client_order_id: str | None = Field(default=None, min_length=36, max_length=36)
    client_created_at: datetime | None = None


class StatusRequest(BaseModel):
    status: str


class ProductVariantRequest(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(ge=0)


class ProductRequest(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=150)
    description: str = "Freshly prepared"
    price: Decimal = Field(default=Decimal("0"), ge=0)
    variants: list[ProductVariantRequest] = Field(default_factory=list)


class UserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)
    role: Literal["cashier", "owner"] = "cashier"


class InventoryItemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    sku: str | None = Field(default=None, max_length=60)
    unit: str = Field(default="pcs", min_length=1, max_length=30)
    quantity: Decimal = Field(default=Decimal("0"), ge=0)
    reorder_level: Decimal = Field(default=Decimal("0"), ge=0)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    supplier: str | None = Field(default=None, max_length=150)


class InventoryAdjustmentRequest(BaseModel):
    quantity: Decimal
    movement_type: Literal["purchase", "adjustment", "waste", "return"] = "adjustment"
    notes: str = ""


class InventoryRecipeRequest(BaseModel):
    inventory_item_id: int
    product_id: int | None = None
    deal_id: int | None = None
    quantity_required: Decimal = Field(gt=0)


class SyncSettingsRequest(BaseModel):
    remote_url: str = Field(min_length=8, max_length=500)
    token: str | None = Field(default=None, max_length=500)


def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def current_user(request: Request, session):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in required")
    user = session.get(User, user_id)
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def owner_only(user: User):
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")


def money_value(value) -> float:
    return float(value or 0)


def period_bounds(period: str, selected: str | None = None):
    try:
        chosen = date.fromisoformat(selected) if selected else None
    except ValueError:
        raise HTTPException(400, "Invalid date")
    return business_period_bounds(period, chosen)


def phone_key(value: str | None) -> str:
    digits = "".join(character for character in (value or "") if character.isdigit())
    if digits.startswith("0092"): digits = digits[4:]
    elif digits.startswith("92"): digits = digits[2:]
    if digits and not digits.startswith("0"): digits = "0" + digits
    return digits


def find_customer_by_phone(session, phone: str | None):
    key = phone_key(phone)
    if not key: return None
    return next((customer for customer in session.scalars(select(Customer).where(Customer.phone.is_not(None)))
                 if phone_key(customer.phone) == key), None)


def serialize_order(order: Order) -> dict:
    return {
        "id": order.id,
        "order_number": order.order_number,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "order_type": order.order_type,
        "payment_method": order.payment_method,
        "status": order.status,
        "approval_status": order.approval_status,
        "cashback_status": order.cashback_status,
        "subtotal": money_value(order.subtotal),
        "discount": money_value(order.discount),
        "tax": money_value(order.tax),
        "total": money_value(order.total),
        "cashback_amount": money_value(order.cashback_amount),
        "cashback_created_at": order.cashback_created_at.isoformat() if order.cashback_created_at else None,
        "net_total": money_value(order_net_total(order)),
    }


@app.on_event("startup")
def startup():
    init_db()
    session = SessionLocal()
    try:
        seed_users(session)
        seed_demo_menu(session)
    finally:
        session.close()
    start_sync_worker()
    ensure_latest_closing()
    start_closing_worker()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/business-status")
def get_business_status():
    return business_status()


@app.get("/")
def index():
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/sw.js")
def service_worker():
    return FileResponse(WEB_ROOT / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.post("/api/login")
def login(payload: LoginRequest, request: Request):
    with SessionLocal() as session:
        user = authenticate(session, payload.username, payload.password, payload.role)
        if not user:
            raise HTTPException(status_code=401, detail="Incorrect credentials")
        request.session["user_id"] = user.id
        return {"username": user.username, "role": user.role}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    with SessionLocal() as session:
        user = current_user(request, session)
        return {"username": user.username, "role": user.role}


@app.get("/api/menu")
def menu(request: Request):
    with SessionLocal() as session:
        user = current_user(request, session)
        categories = []
        for category in session.scalars(select(Category).where(Category.is_active).order_by(Category.display_order, Category.name)):
            products = []
            for product in session.scalars(select(Product).where(Product.category_id == category.id, Product.is_available).order_by(Product.name)):
                variants = session.scalars(select(ProductVariant).where(ProductVariant.product_id == product.id, ProductVariant.is_available).order_by(ProductVariant.id)).all()
                products.append({"id": product.id, "name": product.name, "description": product.description or "", "variants": [{"id": v.id, "name": v.name, "price": money_value(v.price)} for v in variants]})
            categories.append({"id": category.id, "name": category.name, "products": products})
        deals = [{"id": d.id, "name": d.name, "description": d.description or "", "price": money_value(d.price)} for d in session.scalars(select(Deal).where(Deal.is_active).order_by(Deal.id))]
        return {"categories": categories, "deals": deals}


@app.post("/api/orders")
def create_order(payload: CheckoutRequest, request: Request):
    with SessionLocal() as session:
        user = current_user(request, session)
        if payload.client_order_id:
            existing = session.scalar(select(Order).where(Order.client_order_id == payload.client_order_id))
            if existing:
                response = serialize_order(existing)
                response["items"] = []
                response["already_saved"] = True
                return response
        status = business_status(payload.client_created_at)
        if not status["open"]:
            ensure_latest_closing(payload.client_created_at)
            raise HTTPException(status_code=409, detail="Ordering is closed from 1:45 AM until 10:00 AM. The daily closing report has been generated.")
        cart = []
        for line in payload.lines:
            if bool(line.deal_id) == bool(line.variant_id):
                raise HTTPException(400, "Choose either a deal or a product size")
            if line.deal_id:
                deal = session.get(Deal, line.deal_id)
                if not deal or not deal.is_active:
                    raise HTTPException(status_code=400, detail="Deal is no longer available")
                cart.append({"product_id": None, "deal_id": deal.id, "name": deal.name, "unit_price": Decimal(str(deal.price)), "quantity": line.quantity})
                continue
            variant = session.get(ProductVariant, line.variant_id) if line.variant_id else None
            if not variant or not variant.is_available:
                raise HTTPException(status_code=400, detail="Product size is no longer available")
            product = session.get(Product, variant.product_id)
            if not product or not product.is_available:
                raise HTTPException(status_code=400, detail="Product is no longer available")
            cart.append({"product_id": product.id, "variant_id": variant.id, "name": f"{product.name} · {variant.name}", "unit_price": Decimal(str(variant.price)), "quantity": line.quantity})
        customer_id = None
        if payload.order_type.lower() == "delivery":
            if not all(v and v.strip() for v in (payload.customer_name, payload.customer_phone, payload.customer_address)):
                raise HTTPException(status_code=400, detail="Delivery name, phone, and address are required")
            customer = find_customer_by_phone(session, payload.customer_phone)
            if customer:
                customer.name = payload.customer_name.strip()
                customer.phone = payload.customer_phone.strip()
                customer.address = payload.customer_address.strip()
            else:
                customer = Customer(name=payload.customer_name.strip(), phone=payload.customer_phone.strip(), address=payload.customer_address.strip())
                session.add(customer)
            session.flush()
            customer_id = customer.id
        try:
            client_created_at = (payload.client_created_at.astimezone(timezone.utc).replace(tzinfo=None)
                                 if payload.client_created_at else None)
            order = checkout(session, cart, payload.order_type.lower(), payload.payment_method.lower(), customer_id=customer_id,
                             discount=payload.discount, tax_rate=payload.tax_rate, user_id=user.id,
                             client_order_id=payload.client_order_id, created_at=client_created_at)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        response = serialize_order(order)
        response["items"] = [
            {
                "name": item["name"],
                "quantity": int(item["quantity"]),
                "unit_price": money_value(item["unit_price"]),
                "total": money_value(item["unit_price"] * item["quantity"]),
            }
            for item in cart
        ]
        queue_order(payload.client_order_id or "", payload.model_dump(mode="json"))
        return response


@app.post("/api/sync/orders")
def receive_synced_order(payload: CheckoutRequest, x_sync_token: str | None = Header(default=None)):
    """Accept an idempotent checkout from an authorized offline installation."""
    expected = os.getenv("POS_SYNC_TOKEN", "").strip()
    if not expected:
        raise HTTPException(503, "Railway synchronization is not configured on this server")
    if not x_sync_token or not hmac.compare_digest(x_sync_token, expected):
        raise HTTPException(401, "Invalid synchronization token")
    if not payload.client_order_id:
        raise HTTPException(400, "client_order_id is required for synchronized orders")
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.is_active).order_by(User.role.desc(), User.id))
        if not user:
            raise HTTPException(503, "No active POS user is available")

    class InternalSyncRequest:
        def __init__(self, user_id):
            self.session = {"user_id": user_id}

    return create_order(payload, InternalSyncRequest(user.id))


@app.get("/api/management/sync-settings")
def get_sync_settings(request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
    return sync_settings()


@app.get("/api/sync/status")
def get_sync_status(request: Request):
    with SessionLocal() as session:
        current_user(request, session)
    return sync_settings()


@app.put("/api/management/sync-settings")
def update_sync_settings(payload: SyncSettingsRequest, request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
    try:
        return save_sync_settings(payload.remote_url, payload.token)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/management/sync-now")
def run_sync_now(request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
    return sync_pending_orders()


@app.get("/api/dashboard")
def dashboard(request: Request, period: str = "Today", selected_date: str | None = None):
    with SessionLocal() as session:
        current_user(request, session)
        start, end = period_bounds(period, selected_date)
        summary = sales_summary(session, start, end)
        conditions = [Order.status != "cancelled"]
        if start is not None: conditions.append(Order.created_at >= start)
        if end is not None: conditions.append(Order.created_at < end)
        rows = session.execute(select(Product.name, func.sum(OrderItem.quantity)).join(OrderItem, OrderItem.product_id == Product.id).join(Order, Order.id == OrderItem.order_id).where(*conditions).group_by(Product.name).order_by(func.sum(OrderItem.quantity).desc()).limit(10)).all()
        return {"summary": {k: (money_value(v) if isinstance(v, Decimal) else v) for k, v in summary.items()}, "top_items": [{"name": name, "quantity": int(quantity or 0)} for name, quantity in rows]}


@app.get("/api/closing-reports")
def closing_reports(request: Request):
    with SessionLocal() as session:
        current_user(request, session)
        ensure_latest_closing()
        rows = session.scalars(select(DailyClosing).order_by(DailyClosing.closing_date.desc()).limit(90)).all()
        return [serialize_closing(row) for row in rows]


def order_search_condition(search: str):
    """Match everything users can identify in the rendered sales list/details."""
    search_value = search.strip()
    displayed_number = re.sub(r"^order\s*no\s*[-:#]?\s*", "", search_value, flags=re.IGNORECASE)
    term = f"%{search_value}%"
    customer_ids = select(Customer.id).where(or_(Customer.name.ilike(term), Customer.phone.ilike(term),
                                                  Customer.email.ilike(term), Customer.address.ilike(term)))
    product_order_ids = select(OrderItem.order_id).join(Product, OrderItem.product_id == Product.id).where(
        or_(Product.name.ilike(term), Product.description.ilike(term)))
    deal_order_ids = select(OrderItem.order_id).join(Deal, OrderItem.deal_id == Deal.id).where(
        or_(Deal.name.ilike(term), Deal.description.ilike(term)))
    return or_(Order.order_number.ilike(term), Order.order_number.ilike(f"%-{displayed_number}%"),
               Order.order_type.ilike(term), Order.payment_method.ilike(term), Order.status.ilike(term),
               Order.approval_status.ilike(term), Order.cashback_status.ilike(term),
               Order.customer_id.in_(customer_ids), Order.id.in_(product_order_ids),
               Order.id.in_(deal_order_ids))


@app.get("/api/orders")
def orders(request: Request, period: str = "All dates", selected_date: str | None = None, status: str = "all", sort: str = "newest", search: str = ""):
    with SessionLocal() as session:
        current_user(request, session)
        start, end = period_bounds(period, selected_date)
        conditions = []
        if search:
            conditions.append(order_search_condition(search))
        if start is not None: conditions.append(Order.created_at >= start)
        if end is not None: conditions.append(Order.created_at < end)
        if status == "awaiting": conditions.append(Order.approval_status == "awaiting")
        elif status == "approved": conditions.append(Order.approval_status == "approved")
        elif status == "cashback": conditions.append(Order.cashback_status == "pending")
        elif status == "denied": conditions.append(Order.approval_status == "denied")
        ordering = (Order.created_at.asc(), Order.id.asc()) if sort == "oldest" else (Order.total.desc(), Order.created_at.desc()) if sort == "highest" else (Order.total.asc(), Order.created_at.desc()) if sort == "lowest" else (Order.created_at.desc(), Order.id.desc())
        if sort == "number": ordering = (Order.order_number.asc(),)
        return [serialize_order(order) for order in session.scalars(select(Order).where(*conditions).order_by(*ordering))]


@app.get("/api/orders/{order_id}")
def order_detail(order_id: int, request: Request):
    with SessionLocal() as session:
        current_user(request, session)
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        record = serialize_order(order)
        customer = session.get(Customer, order.customer_id) if order.customer_id else None
        record["customer"] = ({"name": customer.name, "phone": customer.phone or "",
                               "address": customer.address or ""} if customer else None)
        items = []
        for item in session.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)):
            product = session.get(Product, item.product_id) if item.product_id else None
            deal = session.get(Deal, item.deal_id) if item.deal_id else None
            items.append({"name": deal.name if deal else product.name if product else "Menu item",
                          "quantity": int(item.quantity or 0), "unit_price": money_value(item.unit_price),
                          "total": money_value(item.total)})
        record["items"] = items
        return record


@app.post("/api/orders/{order_id}/status")
def update_order_status(order_id: int, payload: StatusRequest, request: Request):
    with SessionLocal() as session:
        current_user(request, session)
        order = session.get(Order, order_id)
        if not order or payload.status not in {"approved", "pending", "denied"}:
            raise HTTPException(status_code=400, detail="Invalid order or status")
        if order.approval_status != "awaiting":
            raise HTTPException(409, "This order has already been reviewed")
        order.approval_status = payload.status
        if payload.status == "approved":
            order.status = "completed"
            order.cashback_status = "not_required"
            order.cashback_amount = 0
            order.cashback_created_at = None
        else:
            order.status = payload.status
            order.cashback_status = "pending"
            order.cashback_amount = order.total
            order.cashback_created_at = datetime.now()
        session.commit()
        return serialize_order(order)


@app.get("/api/cashback")
def cashback(request: Request, period: str = "All dates", selected_date: str | None = None,
             status: str = "all", sort: str = "newest", search: str = ""):
    with SessionLocal() as session:
        current_user(request, session)
        start, end = period_bounds(period, selected_date)
        cashback_date = func.coalesce(Order.cashback_created_at, Order.created_at)
        conditions = [Order.cashback_status.in_(("pending", "approved", "rejected"))]
        if start is not None: conditions.append(cashback_date >= start)
        if end is not None: conditions.append(cashback_date < end)
        if status in {"pending", "approved", "rejected"}: conditions.append(Order.cashback_status == status)
        if search:
            term = f"%{search.strip()}%"
            conditions.append(or_(Order.order_number.ilike(term), Order.order_type.ilike(term),
                                  Order.payment_method.ilike(term), Order.status.ilike(term),
                                  Customer.name.ilike(term)))
        ordering = {
            "oldest": (cashback_date.asc(), Order.id.asc()),
            "highest": (Order.cashback_amount.desc(), cashback_date.desc(), Order.id.desc()),
            "lowest": (Order.cashback_amount.asc(), cashback_date.desc(), Order.id.desc()),
            "number": (Order.order_number.asc(), cashback_date.desc(), Order.id.desc()),
            "name": (Customer.name.asc(), cashback_date.desc(), Order.id.desc()),
            "type": (Order.order_type.asc(), cashback_date.desc(), Order.id.desc()),
            "payment": (Order.payment_method.asc(), cashback_date.desc(), Order.id.desc()),
        }.get(sort, (cashback_date.desc(), Order.id.desc()))
        rows = session.execute(select(Order, Customer.name).outerjoin(Customer, Customer.id == Order.customer_id)
                               .where(*conditions).order_by(*ordering)).all()
        records = []
        for order, customer_name in rows:
            record = serialize_order(order)
            record["customer_name"] = customer_name or "Walk-in customer"
            record["cashback_date"] = (order.cashback_created_at or order.created_at).isoformat()
            records.append(record)
        return {
            "records": records,
            "newest": max(records, key=lambda row: (row["cashback_date"] or "", row["id"]), default=None),
            "pending": [row for row in records if row["cashback_status"] == "pending"],
            "approved": [row for row in records if row["cashback_status"] == "approved"],
            "rejected": [row for row in records if row["cashback_status"] == "rejected"],
        }


@app.post("/api/cashback/{order_id}/approve")
def approve_cashback(order_id: int, request: Request):
    with SessionLocal() as session:
        current_user(request, session)
        order = session.get(Order, order_id)
        if not order or order.cashback_status != "pending":
            raise HTTPException(status_code=400, detail="Cashback record is not pending")
        order.cashback_status = "approved"
        session.commit()
        return serialize_order(order)


@app.post("/api/cashback/{order_id}/reject")
def reject_cashback(order_id: int, request: Request):
    with SessionLocal() as session:
        current_user(request, session)
        order = session.get(Order, order_id)
        if not order or order.cashback_status != "pending":
            raise HTTPException(status_code=400, detail="Cashback record is not pending")
        order.cashback_status = "rejected"
        session.commit()
        return serialize_order(order)


@app.get("/api/reports.csv")
def report_csv(request: Request, period: str = "All dates", selected_date: str | None = None, status: str = "all"):
    with SessionLocal() as session:
        current_user(request, session)
        start, end = period_bounds(period, selected_date)
        conditions = []
        if start is not None: conditions.append(Order.created_at >= start)
        if end is not None: conditions.append(Order.created_at < end)
        orders = session.scalars(select(Order).where(*conditions).order_by(Order.created_at.desc(), Order.id.desc())).all()
        if status == "cashback": orders = [o for o in orders if o.cashback_status == "pending"]
        elif status in {"approved", "awaiting", "denied"}: orders = [o for o in orders if o.approval_status == status]
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["Order", "Date", "Type", "Payment", "Approval", "Cashback status", "Gross total", "Cashback deducted", "Net total"])
        for order in orders:
            deducted = order.cashback_amount if order.cashback_status == "approved" else Decimal("0")
            writer.writerow([order.order_number, order.created_at, order.order_type, order.payment_method, order.approval_status, order.cashback_status, f"{order.total or 0:.2f}", f"{deducted or 0:.2f}", f"{order_net_total(order):.2f}"])
        return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=sales_report.csv"})


def simple_pdf(lines: list[str]) -> bytes:
    """Create a dependency-free, paginated A4 text PDF."""
    pages = [lines[index:index + 57] for index in range(0, max(len(lines), 1), 57)] or [[]]
    objects: dict[int, bytes] = {1: b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"}
    page_ids = []
    for index, page_lines in enumerate(pages):
        content_id, page_id = 3 + index * 2, 4 + index * 2
        page_ids.append(page_id)
        commands = ["BT /F1 8 Tf 36 806 Td 12 TL"]
        for line in page_lines:
            safe = line.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({safe[:112]}) Tj T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")
        objects[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        objects[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                            f"/Resources << /Font << /F1 1 0 R >> >> /Contents {content_id} 0 R >>").encode()
    catalog_id = 3 + len(pages) * 2
    objects[2] = ("<< /Type /Pages /Kids [" + " ".join(f"{page_id} 0 R" for page_id in page_ids) +
                  f"] /Count {len(page_ids)} >>").encode()
    objects[catalog_id] = b"<< /Type /Catalog /Pages 2 0 R >>"
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (catalog_id + 1)
    for object_id in range(1, catalog_id + 1):
        offsets[object_id] = len(output)
        output.extend(f"{object_id} 0 obj\n".encode() + objects[object_id] + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {catalog_id + 1}\n0000000000 65535 f \n".encode())
    for object_id in range(1, catalog_id + 1):
        output.extend(f"{offsets[object_id]:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {catalog_id + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(output)


def pdf_report_name(period: str, selected_date: str | None) -> str:
    local_today = datetime.now(BUSINESS_ZONE).date()
    if period == "Specific date" and selected_date:
        suffix = selected_date
    elif period == "Today":
        suffix = business_status()["business_date"]
    elif period == "This week":
        suffix = "week-" + (local_today - timedelta(days=local_today.weekday())).isoformat()
    elif period == "This month":
        suffix = local_today.strftime("%Y-%m")
    else:
        suffix = "all-dates"
    return f"sales-report-{suffix}.pdf"


@app.get("/api/reports.pdf")
def report_pdf(request: Request, period: str = "All dates", selected_date: str | None = None,
               status: str = "all", sort: str = "newest", search: str = ""):
    with SessionLocal() as session:
        current_user(request, session)
        start, end = period_bounds(period, selected_date)
        conditions = [Order.status != "cancelled"]
        if start is not None: conditions.append(Order.created_at >= start)
        if end is not None: conditions.append(Order.created_at < end)
        if status == "cashback": conditions.append(Order.cashback_status == "pending")
        elif status in {"approved", "awaiting", "denied"}: conditions.append(Order.approval_status == status)
        if search:
            conditions.append(order_search_condition(search))
        ordering = {
            "oldest": (Order.created_at.asc(), Order.id.asc()),
            "highest": (Order.total.desc(), Order.created_at.desc()),
            "lowest": (Order.total.asc(), Order.created_at.desc()),
            "number": (Order.order_number.asc(),),
        }.get(sort, (Order.created_at.desc(), Order.id.desc()))
        report_orders = session.scalars(select(Order).where(*conditions).order_by(*ordering)).all()
        gross = sum((money_value(order.total) for order in report_orders), 0.0)
        cashback = sum((money_value(order.cashback_amount) for order in report_orders
                        if order.cashback_status == "approved"), 0.0)
        net = sum((money_value(order_net_total(order)) for order in report_orders), 0.0)
        cash = sum((money_value(order_net_total(order)) for order in report_orders if order.payment_method == "cash"), 0.0)
        online = sum((money_value(order_net_total(order)) for order in report_orders if order.payment_method == "online payment"), 0.0)
        period_label = selected_date if period == "Specific date" and selected_date else period
        lines = ["DECENT PIZZA LIVE", "SALES AND COLD DRINKS REPORT", "",
                 f"Period: {period_label}", f"Status: {status.replace('_', ' ').title()}",
                 f"Search: {search or '-'}", f"Generated: {datetime.now(BUSINESS_ZONE):%d %b %Y %I:%M %p}", "",
                 f"Orders: {len(report_orders)}    Gross: Rs. {gross:,.2f}    Cashback: Rs. {cashback:,.2f}",
                 f"Net sales: Rs. {net:,.2f}    Cash: Rs. {cash:,.2f}    Online: Rs. {online:,.2f}", "",
                 "SALES LIST", "Order                  Date       Type       Payment          Net", "-" * 92]
        for order in report_orders:
            created = order.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_ZONE) if order.created_at else None
            match = re.match(r"^TC-\d{8}-(\d+)$", order.order_number or "")
            display_number = f"Order No-{match.group(1).zfill(3)}" if match else f"Order No-{order.order_number or '-'}"
            date_text = created.strftime('%d-%m-%y') if created else '-'
            time_text = created.strftime('%I:%M %p') if created else '-'
            lines.append(f"{display_number[:22]:22} {date_text:10} {(order.order_type or '-')[:10]:10} "
                         f"{(order.payment_method or '-')[:15]:15} {money_value(order_net_total(order)):10,.2f}")
            lines.append(f"{'':22} {time_text:10}")
    drinks = cold_drinks_report(request, period, selected_date, status, search)
    lines.extend(["", "COLD DRINKS - SOLD SEPARATELY", "Brand                    Size          Quantity       Sales", "-" * 72])
    for row in drinks["direct"]:
        lines.append(f"{row['brand'][:24]:24} {row['size'][:12]:12} {row['quantity']:8}   Rs. {row['revenue']:,.2f}")
    if not drinks["direct"]: lines.append("No separately sold cold drinks for this period.")
    lines.extend(["", "COLD DRINKS INCLUDED IN DEALS", "Deal                             Size          Bottles", "-" * 62])
    for row in drinks["included_in_deals"]:
        lines.append(f"{row['deal'][:32]:32} {row['size'][:12]:12} {row['quantity']:8}")
    if not drinks["included_in_deals"]: lines.append("No deal cold drinks for this period.")
    filename = pdf_report_name(period, selected_date)
    return StreamingResponse(iter([simple_pdf(lines)]), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def deal_drink_sizes(description: str) -> list[tuple[str, int]]:
    """Return normalized bottle sizes and counts declared by a deal."""
    text_value = description or ""
    results: list[tuple[str, int]] = []
    pattern = re.compile(r"(?:(\d+)\s*[x×]\s*)?(\d+(?:\.\d+)?)\s*(ml|lit(?:er|re)s?)\s+drinks?", re.I)
    for match in pattern.finditer(text_value):
        multiplier = int(match.group(1) or 1)
        amount = Decimal(match.group(2))
        milliliters = int(amount if match.group(3).lower() == "ml" else amount * 1000)
        # Menu wording alternates between 2.2L and 2.25L for the same large bottle.
        if 2200 <= milliliters <= 2250:
            milliliters = 2200
        results.append((f"{milliliters}ml", multiplier))
    if not results:
        unspecified = re.search(r"(\d+)\s+(?:red\s+)?drinks?", text_value, re.I)
        if unspecified:
            results.append(("Unspecified", int(unspecified.group(1))))
    return results


@app.get("/api/cold-drinks-report")
def cold_drinks_report(request: Request, period: str = "All dates", selected_date: str | None = None,
                       status: str = "all", search: str = ""):
    with SessionLocal() as session:
        current_user(request, session)
        start, end = period_bounds(period, selected_date)
        conditions = [Order.status != "cancelled"]
        if start is not None: conditions.append(Order.created_at >= start)
        if end is not None: conditions.append(Order.created_at < end)
        if status == "cashback": conditions.append(Order.cashback_status == "pending")
        elif status in {"approved", "awaiting", "denied"}: conditions.append(Order.approval_status == status)
        orders = session.scalars(select(Order).where(*conditions)).all()
        direct: dict[tuple[str, str], dict] = {}
        deal_rows: dict[tuple[str, str], int] = defaultdict(int)
        order_ids = [order.id for order in orders]
        items = (session.scalars(select(OrderItem).where(OrderItem.order_id.in_(order_ids))).all()
                 if order_ids else [])
        for item in items:
            quantity = int(item.quantity or 0)
            if item.deal_id:
                deal = session.get(Deal, item.deal_id)
                if not deal:
                    continue
                for size, bottles_per_deal in deal_drink_sizes(deal.description or ""):
                    deal_rows[(deal.name, size)] += quantity * bottles_per_deal
                continue
            product = session.get(Product, item.product_id) if item.product_id else None
            category = session.get(Category, product.category_id) if product else None
            if not product or not category or category.name != "Cold Drinks":
                continue
            variant = session.get(ProductVariant, item.product_variant_id) if item.product_variant_id else None
            if not variant:
                matches = session.scalars(select(ProductVariant).where(
                    ProductVariant.product_id == product.id,
                    ProductVariant.price == item.unit_price)).all()
                variant = matches[0] if len(matches) == 1 else None
            size = variant.name if variant else "Unknown size"
            key = (product.name, size)
            row = direct.setdefault(key, {"brand": product.name, "size": size, "quantity": 0, "revenue": 0.0})
            row["quantity"] += quantity
            row["revenue"] = round(row["revenue"] + float(item.total or 0), 2)
        size_order = {name: index for index, name in enumerate(("250ml", "500ml", "1000ml", "1500ml", "2200ml", "Unspecified", "Unknown size"))}
        direct_rows = sorted(direct.values(), key=lambda row: (row["brand"], size_order.get(row["size"], 99)))
        included_rows = [{"deal": deal, "size": size, "quantity": quantity}
                         for (deal, size), quantity in sorted(deal_rows.items(), key=lambda row: (row[0][0], size_order.get(row[0][1], 99)))]
        if search:
            needle = search.strip().lower()
            direct_rows = [row for row in direct_rows
                           if needle in f"{row['brand']} {row['size']} {row['quantity']} {row['revenue']}".lower()]
            included_rows = [row for row in included_rows
                             if needle in f"{row['deal']} {row['size']} {row['quantity']}".lower()]
        direct_units = sum(row["quantity"] for row in direct_rows)
        deal_units = sum(row["quantity"] for row in included_rows)
        return {"summary": {"direct_units": direct_units, "deal_units": deal_units,
                            "total_units": direct_units + deal_units,
                            "direct_revenue": round(sum(row["revenue"] for row in direct_rows), 2)},
                "direct": direct_rows, "included_in_deals": included_rows}


@app.get("/api/management/categories")
def management_categories(request: Request):
    with SessionLocal() as session:
        user = current_user(request, session); owner_only(user)
        return [{"id": c.id, "name": c.name} for c in session.scalars(select(Category).where(Category.is_active).order_by(Category.display_order, Category.name))]


@app.post("/api/management/products")
def add_product(payload: ProductRequest, request: Request):
    with SessionLocal() as session:
        user = current_user(request, session); owner_only(user)
        category = session.get(Category, payload.category_id)
        if not category: raise HTTPException(status_code=400, detail="Category not found")
        if not payload.name.strip(): raise HTTPException(400, "Enter a product name")
        product = Product(name=payload.name.strip(), description=payload.description.strip(), category_id=category.id)
        session.add(product); session.flush()
        variants = payload.variants or [ProductVariantRequest(name="Regular", price=payload.price)]
        for variant in variants:
            session.add(ProductVariant(product_id=product.id, name=variant.name.strip(), price=variant.price))
        if category.name == "Deals":
            session.add(Deal(name=product.name, description=product.description, price=payload.price, is_active=True))
        session.commit()
        return {"id": product.id, "name": product.name}


@app.post("/api/management/users")
def save_user(payload: UserRequest, request: Request):
    with SessionLocal() as session:
        user = current_user(request, session); owner_only(user)
        if not payload.username.strip(): raise HTTPException(400, "Enter a username")
        target = session.scalar(select(User).where(User.username == payload.username.strip()))
        if not target:
            target = User(username=payload.username.strip(), role=payload.role, password_hash=password_hash(payload.password)); session.add(target)
        else:
            target.role = payload.role; target.password_hash = password_hash(payload.password); target.is_active = True
        session.commit(); return {"username": target.username, "role": target.role}

class CustomerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    phone: str = Field(min_length=1, max_length=30)
    email: str = ""
    address: str = Field(min_length=1)


@app.get("/api/guests")
@app.get("/api/customers")
def customers(request: Request, search: str = ""):
    with SessionLocal() as session:
        current_user(request, session)
        return [{"id": c.id, "name": c.name, "phone": c.phone, "email": c.email, "address": c.address}
                for c in session.scalars(select(Customer).order_by(Customer.name))
                if search.lower() in f"{c.name} {c.phone or ''} {c.email or ''}".lower()]


@app.post("/api/guests")
@app.post("/api/customers")
def add_customer(payload: CustomerRequest, request: Request):
    with SessionLocal() as session:
        current_user(request, session)
        customer = find_customer_by_phone(session, payload.phone)
        updated = customer is not None
        if customer:
            customer.name, customer.phone = payload.name.strip(), payload.phone.strip()
            customer.email, customer.address = payload.email.strip(), payload.address.strip()
        else:
            customer = Customer(**{k: v.strip() for k, v in payload.model_dump().items()})
            session.add(customer)
        session.commit(); return {"id": customer.id, "updated": updated}


@app.put("/api/customers/{customer_id}")
def update_customer(customer_id: int, payload: CustomerRequest, request: Request):
    with SessionLocal() as session:
        current_user(request, session)
        customer = session.get(Customer, customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        duplicate = find_customer_by_phone(session, payload.phone)
        if duplicate and duplicate.id != customer.id:
            raise HTTPException(status_code=409, detail="Another customer already uses this phone number")
        customer.name = payload.name.strip()
        customer.phone = payload.phone.strip()
        customer.email = payload.email.strip()
        customer.address = payload.address.strip()
        session.commit()
        return {"id": customer.id, "updated": True}


@app.delete("/api/customers/{customer_id}")
def delete_customer(customer_id: int, request: Request):
    with SessionLocal() as session:
        current_user(request, session)
        customer = session.get(Customer, customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        # Preserve historical orders while removing the directory entry.
        for order in session.scalars(select(Order).where(Order.customer_id == customer.id)):
            order.customer_id = None
        session.delete(customer)
        session.commit()
        return {"deleted": True, "id": customer_id}


@app.get("/api/customers/lookup")
def customer_lookup(request: Request, phone: str = ""):
    with SessionLocal() as session:
        current_user(request, session)
        customer = find_customer_by_phone(session, phone)
        if not customer: return {"found": False}
        return {"found": True, "id": customer.id, "name": customer.name, "phone": customer.phone,
                "email": customer.email or "", "address": customer.address or ""}


@app.get("/api/management/products")
def managed_products(request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
        result = []
        products = session.scalars(
            select(Product)
            .outerjoin(Category, Product.category_id == Category.id)
            .where(Product.is_available)
            .order_by(Category.display_order, Category.name, Product.name, Product.id)
        )
        for p in products:
            variants = list(session.scalars(select(ProductVariant).where(
                ProductVariant.product_id == p.id, ProductVariant.is_available).order_by(ProductVariant.id)))
            v = variants[0] if variants else None
            category = session.get(Category, p.category_id)
            result.append({"id": p.id, "category_id": p.category_id, "category": category.name if category else "Uncategorized",
                           "name": p.name, "description": p.description or "", "price": money_value(v.price if v else p.price),
                           "variants": [{"id": item.id, "name": item.name, "price": money_value(item.price)} for item in variants]})
        return result


@app.put("/api/management/products/{product_id}")
def edit_product(product_id: int, payload: ProductRequest, request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
        p = session.get(Product, product_id)
        if not p: raise HTTPException(404, "Product not found")
        if not payload.name.strip(): raise HTTPException(400, "Enter a product name")
        category = session.get(Category, payload.category_id)
        if not category: raise HTTPException(400, "Category not found")
        old_name = p.name
        old_category = session.get(Category, p.category_id)
        p.name, p.description, p.category_id = payload.name.strip(), payload.description.strip(), category.id
        existing_variants = {variant.id: variant for variant in session.scalars(
            select(ProductVariant).where(ProductVariant.product_id == p.id))}
        if payload.variants:
            submitted_ids = set()
            for item in payload.variants:
                variant = existing_variants.get(item.id) if item.id else None
                if not variant:
                    variant = ProductVariant(product_id=p.id); session.add(variant)
                variant.name, variant.price, variant.is_available = item.name.strip(), item.price, True
                session.flush()
                submitted_ids.add(variant.id)
            for variant_id, variant in existing_variants.items():
                if variant_id not in submitted_ids:
                    variant.is_available = False
        else:
            v = next(iter(existing_variants.values()), None)
            if not v:
                v = ProductVariant(product_id=p.id)
                session.add(v)
            v.name, v.price, v.is_available = "Regular", payload.price, True
            for variant in existing_variants.values():
                if variant is not v:
                    variant.is_available = False
        deal = session.scalar(select(Deal).where(Deal.name == old_name))
        if category.name == "Deals":
            if not deal:
                deal = session.scalar(select(Deal).where(Deal.name == p.name))
            if not deal:
                deal = Deal(name=p.name); session.add(deal)
            deal.name, deal.description, deal.price, deal.is_active = p.name, p.description, payload.price, True
        elif old_category and old_category.name == "Deals" and deal:
            deal.is_active = False
        session.commit()
        return {"ok": True}


@app.delete("/api/management/products/{product_id}")
def deactivate_product(product_id: int, request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
        p = session.get(Product, product_id)
        if not p: raise HTTPException(404, "Product not found")
        p.is_available = False
        category = session.get(Category, p.category_id)
        if category and category.name == "Deals":
            deal = session.scalar(select(Deal).where(Deal.name == p.name))
            if deal: deal.is_active = False
        session.commit()
        return {"ok": True}


@app.get("/api/management/users")
def users(request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
        return [{"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active} for u in session.scalars(select(User).order_by(User.role, User.username))]


@app.post("/api/management/users/{user_id}/toggle")
def toggle_user(user_id: int, request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
        u = session.get(User, user_id)
        if not u: raise HTTPException(404, "User not found")
        u.is_active = not u.is_active; session.commit()
        return {"ok": True}


@app.get("/api/management/backup")
def backup_database(request: Request):
    # A portable logical backup works with both SQLite and hosted PostgreSQL.
    from app.database.database import Base, engine
    from fastapi.encoders import jsonable_encoder
    with SessionLocal() as session:
        owner_only(current_user(request, session))
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        with connection.begin():
            tables = {table.name: [dict(row) for row in connection.execute(select(table)).mappings()]
                      for table in Base.metadata.sorted_tables}
    return JSONResponse(jsonable_encoder({"format": "top-city-pos-v1", "tables": tables}),
                        headers={"Content-Disposition": "attachment; filename=top_city_backup.json"})


def inventory_record(item: InventoryItem) -> dict:
    return {"id": item.id, "name": item.name, "sku": item.sku or "", "unit": item.unit,
            "quantity": float(item.quantity or 0), "reorder_level": float(item.reorder_level or 0),
            "unit_cost": float(item.unit_cost or 0), "supplier": item.supplier or "",
            "low_stock": (item.quantity or 0) <= (item.reorder_level or 0), "is_active": item.is_active}


@app.get("/api/inventory")
def inventory(request: Request, search: str = ""):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
        items = list(session.scalars(select(InventoryItem).where(InventoryItem.is_active).order_by(InventoryItem.name)))
        if search: items = [i for i in items if search.lower() in f"{i.name} {i.sku or ''} {i.supplier or ''}".lower()]
        movements = session.execute(select(InventoryMovement, InventoryItem.name).join(InventoryItem).order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc()).limit(100)).all()
        recipes = session.execute(select(InventoryRecipe, InventoryItem.name, Product.name, Deal.name)
                    .join(InventoryItem, InventoryItem.id == InventoryRecipe.inventory_item_id)
                    .outerjoin(Product, Product.id == InventoryRecipe.product_id)
                    .outerjoin(Deal, Deal.id == InventoryRecipe.deal_id).order_by(Product.name, Deal.name, InventoryItem.name)).all()
        return {"items": [inventory_record(i) for i in items],
                "summary": {"items": len(items), "low": sum((i.quantity or 0) <= (i.reorder_level or 0) for i in items),
                            "value": float(sum(((i.quantity or 0) * (i.unit_cost or 0) for i in items), Decimal(0)))},
                "movements": [{"id": m.id, "item": name, "quantity": float(m.quantity), "type": m.movement_type,
                               "notes": m.notes or "", "created_at": m.created_at.isoformat()} for m, name in movements],
                "recipes": [{"id": r.id, "item": item, "target": product or deal, "target_type": "Product" if r.product_id else "Deal",
                             "quantity": float(r.quantity_required)} for r, item, product, deal in recipes],
                "products": [{"id": p.id, "name": p.name} for p in session.scalars(select(Product).where(Product.is_available).order_by(Product.name))],
                "deals": [{"id": d.id, "name": d.name} for d in session.scalars(select(Deal).where(Deal.is_active).order_by(Deal.id))]}


@app.post("/api/inventory/items")
def add_inventory_item(payload: InventoryItemRequest, request: Request):
    with SessionLocal() as session:
        user = current_user(request, session); owner_only(user)
        if session.scalar(select(InventoryItem).where(func.lower(InventoryItem.name) == payload.name.strip().lower())):
            raise HTTPException(409, "Inventory item already exists")
        item = InventoryItem(name=payload.name.strip(), sku=(payload.sku or "").strip() or None, unit=payload.unit.strip(),
                             quantity=payload.quantity, reorder_level=payload.reorder_level, unit_cost=payload.unit_cost,
                             supplier=(payload.supplier or "").strip() or None)
        session.add(item); session.flush()
        if payload.quantity:
            session.add(InventoryMovement(inventory_item_id=item.id, user_id=user.id, quantity=payload.quantity,
                                          movement_type="opening", notes="Opening balance"))
        session.commit(); return inventory_record(item)


@app.put("/api/inventory/items/{item_id}")
def edit_inventory_item(item_id: int, payload: InventoryItemRequest, request: Request):
    with SessionLocal() as session:
        user = current_user(request, session); owner_only(user); item = session.get(InventoryItem, item_id)
        if not item: raise HTTPException(404, "Inventory item not found")
        quantity_change = payload.quantity - (item.quantity or 0)
        item.name, item.sku, item.unit = payload.name.strip(), (payload.sku or "").strip() or None, payload.unit.strip()
        item.quantity, item.reorder_level, item.unit_cost = payload.quantity, payload.reorder_level, payload.unit_cost
        item.supplier = (payload.supplier or "").strip() or None
        if quantity_change:
            session.add(InventoryMovement(inventory_item_id=item.id, user_id=user.id, quantity=quantity_change,
                                          movement_type="adjustment", notes="Quantity changed while editing item"))
        session.commit(); return inventory_record(item)


@app.post("/api/inventory/items/{item_id}/adjust")
def adjust_inventory(item_id: int, payload: InventoryAdjustmentRequest, request: Request):
    with SessionLocal() as session:
        user = current_user(request, session); owner_only(user); item = session.get(InventoryItem, item_id)
        if not item: raise HTTPException(404, "Inventory item not found")
        change = abs(payload.quantity) if payload.movement_type in {"purchase", "return"} else -abs(payload.quantity) if payload.movement_type == "waste" else payload.quantity
        if (item.quantity or 0) + change < 0: raise HTTPException(409, "Adjustment would make stock negative")
        item.quantity = (item.quantity or 0) + change
        session.add(InventoryMovement(inventory_item_id=item.id, user_id=user.id, quantity=change,
                                      movement_type=payload.movement_type, notes=payload.notes.strip()))
        session.commit(); return inventory_record(item)


@app.post("/api/inventory/recipes")
def add_inventory_recipe(payload: InventoryRecipeRequest, request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session))
        if bool(payload.product_id) == bool(payload.deal_id): raise HTTPException(400, "Choose one product or deal")
        if not session.get(InventoryItem, payload.inventory_item_id): raise HTTPException(404, "Inventory item not found")
        conditions = [InventoryRecipe.inventory_item_id == payload.inventory_item_id]
        conditions.append(InventoryRecipe.product_id == payload.product_id if payload.product_id else InventoryRecipe.deal_id == payload.deal_id)
        recipe = session.scalar(select(InventoryRecipe).where(*conditions))
        if recipe: recipe.quantity_required = payload.quantity_required
        else: recipe = InventoryRecipe(**payload.model_dump()); session.add(recipe)
        session.commit(); return {"id": recipe.id}


@app.delete("/api/inventory/recipes/{recipe_id}")
def delete_inventory_recipe(recipe_id: int, request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session)); recipe = session.get(InventoryRecipe, recipe_id)
        if not recipe: raise HTTPException(404, "Recipe line not found")
        session.delete(recipe); session.commit(); return {"ok": True}


@app.delete("/api/inventory/items/{item_id}")
def deactivate_inventory_item(item_id: int, request: Request):
    with SessionLocal() as session:
        owner_only(current_user(request, session)); item = session.get(InventoryItem, item_id)
        if not item: raise HTTPException(404, "Inventory item not found")
        for recipe in session.scalars(select(InventoryRecipe).where(InventoryRecipe.inventory_item_id == item.id)).all():
            session.delete(recipe)
        for movement in session.scalars(select(InventoryMovement).where(InventoryMovement.inventory_item_id == item.id)).all():
            session.delete(movement)
        session.delete(item); session.commit(); return {"ok": True}
