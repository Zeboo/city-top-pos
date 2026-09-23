from __future__ import annotations

import csv
import hmac
import io
import os
import secrets
from datetime import date, datetime, timezone
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
from app.models import (Category, Customer, Deal, InventoryItem, InventoryMovement, InventoryRecipe,
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


class ProductRequest(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=150)
    description: str = "Freshly prepared"
    price: Decimal = Field(default=Decimal("0"), ge=0)


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


@app.get("/health")
def health():
    return {"status": "ok"}


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


@app.get("/api/orders")
def orders(request: Request, period: str = "All dates", selected_date: str | None = None, status: str = "all", sort: str = "newest", search: str = ""):
    with SessionLocal() as session:
        current_user(request, session)
        start, end = period_bounds(period, selected_date)
        conditions = []
        if search:
            conditions.append(or_(*(column.ilike(f"%{search}%") for column in (Order.order_number, Order.order_type, Order.payment_method, Order.status))))
        if start is not None: conditions.append(Order.created_at >= start)
        if end is not None: conditions.append(Order.created_at < end)
        if status == "awaiting": conditions.append(Order.approval_status == "awaiting")
        elif status == "approved": conditions.append(Order.approval_status == "approved")
        elif status == "cashback": conditions.append(Order.cashback_status == "pending")
        elif status == "denied": conditions.append(Order.approval_status == "denied")
        ordering = (Order.created_at.asc(), Order.id.asc()) if sort == "oldest" else (Order.total.desc(), Order.created_at.desc()) if sort == "highest" else (Order.total.asc(), Order.created_at.desc()) if sort == "lowest" else (Order.created_at.desc(), Order.id.desc())
        if sort == "number": ordering = (Order.order_number.asc(),)
        return [serialize_order(order) for order in session.scalars(select(Order).where(*conditions).order_by(*ordering))]


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
        conditions = [Order.cashback_status.in_(("pending", "approved"))]
        if start is not None: conditions.append(cashback_date >= start)
        if end is not None: conditions.append(cashback_date < end)
        if status in {"pending", "approved"}: conditions.append(Order.cashback_status == status)
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
        session.add(product); session.flush(); session.add(ProductVariant(product_id=product.id, name="Regular", price=payload.price))
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
        for p in session.scalars(select(Product).where(Product.is_available).order_by(Product.name)):
            v = session.scalar(select(ProductVariant).where(ProductVariant.product_id == p.id).order_by(ProductVariant.id))
            category = session.get(Category, p.category_id)
            result.append({"id": p.id, "category_id": p.category_id, "category": category.name if category else "Uncategorized",
                           "name": p.name, "description": p.description or "", "price": money_value(v.price if v else p.price)})
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
        v = session.scalar(select(ProductVariant).where(ProductVariant.product_id == p.id).order_by(ProductVariant.id))
        if v: v.price = payload.price
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
