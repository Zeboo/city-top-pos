from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (Category, Deal, InventoryItem, InventoryMovement, InventoryRecipe,
                        Order, OrderItem, Payment, Product, ProductVariant, User)

CENT = Decimal("0.01")
BUSINESS_ZONE = timezone(timedelta(hours=5), name="Asia/Karachi")


def password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def seed_users(session: Session) -> None:
    accounts = (("owner", "owner123", "owner"), ("cashier", "cashier123", "cashier"))
    existing = {user.username for user in session.scalars(select(User))}
    for username, password, role in accounts:
        if username not in existing:
            session.add(User(username=username, password_hash=password_hash(password), role=role))
    session.commit()


def authenticate(session: Session, username: str, password: str, role: str) -> User | None:
    user = session.scalar(select(User).where(User.username == username.strip(), User.role == role, User.is_active))
    return user if user and user.password_hash == password_hash(password) else None


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def business_period_bounds(period: str, selected_date: date | None = None) -> tuple[datetime | None, datetime | None]:
    """Return UTC-naive database bounds for a Pakistan-local business period.

    SQLite server timestamps are UTC-naive values. UI date filters are business
    dates in Asia/Karachi, so converting the local boundaries prevents late-night
    sales from appearing under the previous/next day.
    """
    local_now = datetime.now(BUSINESS_ZONE)
    if period == "Today":
        business_date = local_now.date() - timedelta(days=1) if local_now.time() < time(2) else local_now.date()
        local_start = datetime.combine(business_date, time(10), BUSINESS_ZONE)
        local_end = datetime.combine(business_date + timedelta(days=1), time(2), BUSINESS_ZONE)
    elif period == "Specific date" and selected_date is not None:
        local_start = datetime.combine(selected_date, time(10), BUSINESS_ZONE)
        local_end = datetime.combine(selected_date + timedelta(days=1), time(2), BUSINESS_ZONE)
    elif period == "This week":
        local_start = datetime.combine(local_now.date() - timedelta(days=local_now.weekday()), time.min, BUSINESS_ZONE)
        local_end = local_start + timedelta(days=7)
    elif period == "This month":
        local_start = datetime(local_now.year, local_now.month, 1, tzinfo=BUSINESS_ZONE)
        local_end = datetime(local_now.year + (local_now.month == 12), 1 if local_now.month == 12 else local_now.month + 1, 1, tzinfo=BUSINESS_ZONE)
    else:
        return None, None
    return (local_start.astimezone(timezone.utc).replace(tzinfo=None),
            local_end.astimezone(timezone.utc).replace(tzinfo=None))


def seed_demo_menu(session: Session) -> None:
    """Create a useful starter menu once; all records remain editable in SQLite."""
    categories = {category.name: category for category in session.scalars(select(Category))}
    category_names = ("Pizza", "Burgers", "Shawarma", "Roll Paratha", "Starters", "Wrap", "Pasta", "Fries", "Sandwiches", "Deals")
    for name in category_names:
        if name not in categories:
            categories[name] = Category(name=name, display_order=len(categories))
            session.add(categories[name])
    session.flush()
    category_order = {"Pizza": 0, "Fries": 2, "Drinks": 3, "Burgers": 4, "Shawarma": 5,
                      "Roll Paratha": 6, "Starters": 7, "Wrap": 8, "Pasta": 9,
                      "Sandwiches": 10, "Deals": 11}
    for name, order in category_order.items():
        if name in categories:
            categories[name].display_order = order
            categories[name].is_active = True
    for legacy_name in ("Classic Pizzas", "Specialty Pizzas", "Sides"):
        legacy = categories.get(legacy_name)
        if legacy:
            legacy.is_active = False
    menu = [
        ("Tikka Pizza", "Pizza", (650, 1100, 1500, 1980)), ("Fajita Pizza", "Pizza", (650, 1100, 1500, 1980)),
        ("Kabab Pizza", "Pizza", (700, 1150, 1600, 2100)), ("Cheese Lover", "Pizza", (700, 1150, 1600, 2100)),
        ("Hot & Spicy Pizza", "Pizza", (650, 1100, 1500, 1980)), ("BBQ Pizza", "Pizza", (650, 1100, 1500, 1980)),
        ("Vegetable Pizza", "Pizza", (650, 1100, 1500, 1980)), ("All Topping", "Pizza", (700, 1150, 1600, 2100)),
        ("Malai Boti Pizza", "Pizza", (750, 1200, 1800, 2300)), ("Special Decent Pizza", "Pizza", (750, 1200, 1800, 2300)), ("Crown Crust", "Pizza", (850, 1350, 1900, 2500)),
        ("Chicken Tikka Burger", "Burgers", (300,)), ("Chicken Fajita Burger", "Burgers", (300,)), ("Zinger Burger", "Burgers", (350,)), ("Chicken Patty Burger", "Burgers", (300,)), ("Grill Cheese Burger", "Burgers", (380,)), ("Zinger Cheese Burger", "Burgers", (440,)), ("Double Dose Burger", "Burgers", (550,)),
        ("Zinger Shawarma", "Shawarma", (300,)), ("Shashlik Shawarma", "Shawarma", (350,)), ("Chicken Tikka Shawarma", "Shawarma", (240,)), ("Chicken Fajita Shawarma", "Shawarma", (240,)), ("Kabab Shawarma", "Shawarma", (280,)),
        ("Tikka Roll Paratha", "Roll Paratha", (300,)), ("Fajita Roll Paratha", "Roll Paratha", (300,)), ("Chicken & Cheese Roll Paratha", "Roll Paratha", (350,)), ("Arab Roll", "Roll Paratha", (300,)), ("Zinger Roll Paratha", "Roll Paratha", (350,)),
        ("Chicken Zinger Pcs", "Starters", (300,)), ("Crispy Wings 3 Pcs", "Starters", (200,)), ("Crispy Wings 6 Pcs", "Starters", (380,)), ("Crispy Wings 12 Pcs", "Starters", (760,)), ("Nuggets 6 Pcs", "Starters", (350,)), ("Nuggets 12 Pcs", "Starters", (650,)),
        ("Zinger Wrap", "Wrap", (450,)), ("Special Decent Wrap", "Wrap", (500,)),
        ("Special Decent Pasta Regular", "Pasta", (550,)), ("Special Decent Pasta Large", "Pasta", (880,)),
        ("Loaded Fries Regular", "Fries", (480,)), ("Loaded Fries Large", "Fries", (800,)), ("Plain Fries", "Fries", (250,)), ("Mayo Garlic Fries", "Fries", (300,)),
        ("Club Sandwich", "Sandwiches", (220,)), ("Tikka Sandwich", "Sandwiches", (240,)), ("Grill Cheese Sandwich", "Sandwiches", (300,)),
    ]
    existing_products = {product.name: product for product in session.scalars(select(Product))}
    for name, category, prices in menu:
        product = existing_products.get(name)
        if product is None:
            product = Product(name=name, category_id=categories[category].id,
                              description=f"Fresh {name.lower()} made to order", is_available=True)
            session.add(product)
            session.flush()
        variant_names = ("S 8\"", "M 11\"", "L 14\"", "XL 16\"") if category == "Pizza" else ("Regular",)
        existing_variants = {variant.name: variant for variant in session.scalars(select(ProductVariant).where(ProductVariant.product_id == product.id))}
        for variant_name, price in zip(variant_names, prices):
            variant = existing_variants.get(variant_name)
            if variant is None:
                session.add(ProductVariant(product_id=product.id, name=variant_name, price=price))
    for obsolete_name in ("Chicken & Pickel", "Loaded Fries"):
        obsolete = existing_products.get(obsolete_name)
        if obsolete:
            obsolete.is_available = False
    deals = [
        ("Deal 1", "1 Zinger Burger, 3 Crispy Wings, 1 Liter Drink", 580),
        ("Deal 2", "2 Zinger Burgers, 3 Crispy Wings, 1 Liter Drink", 980),
        ("Deal 3", "1 Small Pizza, 1 Zinger Burger, Fries & 1 Liter Drink", 1300),
        ("Deal 4", "2 Small Pizzas, 1 Liter Drink", 1350),
        ("Deal 5", "1 Small Pizza, 1 Zinger Burger, 3 Crispy Wings, 3 Nuggets, 1 Plain Fries, 1 Liter Drink", 1600),
        ("Deal 6", "5 Zinger Burgers, 1.5 Liter Drink", 1750),
        ("Deal 7", "2 Medium Pizzas, 6 Crispy Wings, 1.5 Liter Drink", 2450),
        ("Deal 8", "2 Large Pizzas, 6 Spicy Wings, 2.25 Liter Drink", 3300),
        ("Deal 9", "1 Pound Cake, 1 Large Pizza, 6 Crispy Wings, 6 Nuggets, 1 Plain Fries, 1.5 Liter Drink", 3000),
        ("Deal 10", "3 Pound Cake, 1 Large Pizza, 12 Crispy Wings, 12 Nuggets, 2 Plain Fries, 2 x 1.5 Liter Drinks", 5450),
        ("Deal 11", "2 Zinger Shawarmas with 500ml Drink", 650),
        ("Deal 12", "1 XL Crown Crust Pizza, 6 Crispy Wings, 6 Nuggets, 1 Plain Fries, 1.5 Liter Drink", 3350),
        ("Deal 13", "2 Roll Parathas with 500ml Drink", 650),
        ("Deal 14", "4 Roll Parathas with 1 Liter Drink", 1250),
        ("Deal 15", "3 Zinger Burgers with 1 Liter Drink", 1100),
        ("Deal 16", "12 Spicy Wings, 12 Nuggets with 1.5 Liter Drink", 1450),
        ("Deal 17", "1 XL Pizza, 6 Wings, 6 Nuggets, 1.5 Liter Drink", 2700),
        ("Deal 18", "2 XL Pizzas, 6 Wings, 2 Plain Fries, 2 x 1.5 Liter Drinks", 4950),
        ("Deal 19", "2 Arab Rolls, 1 Plain Fries, 6 Wings, 1 Liter Drink", 1250),
        ("Deal 20", "1 Arab Roll, 3 Wings, 1 Red Drink", 500),
        ("Deal 21", "1 Large Pizza, 6 Crispy Wings, 1 Red Pasta, 1.5 Liter Drink", 2400),
        ("Deal 22", "1 Medium Pizza, 1 Plain Fries, 1 Liter Drink", 1350),
        ("Deal 23", "1 Medium Crown Crust Pizza, 1 Red Pasta, 1 Liter Drink", 1900),
        ("Deal 24", "1 Large Crown Crust Pizza, 1 Special Red Pasta, 1 Decent Special Wrap, 1.5 Liter Drink", 2900),
    ]
    existing_deals = {deal.name: deal for deal in session.scalars(select(Deal))}
    for name, description, price in deals:
        if name in existing_deals:
            deal = existing_deals[name]
            # Preserve prices and descriptions saved from Management. Deal 2's
            # former Rs. 950 default is the only versioned seed correction.
            if name == "Deal 2" and deal.price == Decimal("950"):
                deal.price = Decimal("980")
        else:
            session.add(Deal(name=name, description=description, price=price, is_active=True))
    session.flush()
    existing_products = {product.name for product in session.scalars(select(Product))}
    for name, description, price in deals:
        if name in existing_products:
            product = session.scalar(select(Product).where(Product.name == name))
            variant = session.scalar(select(ProductVariant).where(ProductVariant.product_id == product.id))
            continue
        product = Product(name=name, category_id=categories["Deals"].id, description=description)
        session.add(product)
        session.flush()
        session.add(ProductVariant(product_id=product.id, name="Package", price=price))

    # Deals appear in Management as products but are sold from the deals table.
    # Keep both representations synchronized and retire accidental duplicates.
    session.flush()
    deal_records = {deal.name: deal for deal in session.scalars(select(Deal).order_by(Deal.id))}
    deal_products: dict[str, list[Product]] = {}
    for product in session.scalars(select(Product).where(Product.category_id == categories["Deals"].id).order_by(Product.id)):
        deal_products.setdefault(product.name, []).append(product)
    for name, matching_products in deal_products.items():
        primary = next((product for product in matching_products if product.is_available), matching_products[0])
        for duplicate in matching_products:
            if duplicate.id != primary.id:
                duplicate.is_available = False
        variant = session.scalar(select(ProductVariant).where(ProductVariant.product_id == primary.id).order_by(ProductVariant.id))
        deal = deal_records.get(name)
        if deal and variant:
            deal.description = primary.description
            deal.price = variant.price
            deal.is_active = primary.is_available
    session.commit()


def checkout(session: Session, cart: list[dict], order_type: str, payment_method: str,
             customer_id: int | None = None, discount: Decimal = Decimal("0"), tax_rate: Decimal = Decimal("0"),
             user_id: int | None = None, client_order_id: str | None = None,
             created_at: datetime | None = None) -> Order:
    if not cart:
        raise ValueError("The order cart is empty")
    required: dict[int, Decimal] = {}
    for line in cart:
        conditions = ([InventoryRecipe.product_id == line.get("product_id")] if line.get("product_id") else
                      [InventoryRecipe.deal_id == line.get("deal_id")])
        for recipe in session.scalars(select(InventoryRecipe).where(*conditions)):
            required[recipe.inventory_item_id] = required.get(recipe.inventory_item_id, Decimal(0)) + Decimal(str(recipe.quantity_required)) * int(line["quantity"])
    inventory = {item_id: session.get(InventoryItem, item_id) for item_id in required}
    shortages = [f"{inventory[item_id].name} ({inventory[item_id].quantity} {inventory[item_id].unit} available)"
                 if inventory[item_id] else f"Inventory item #{item_id} is missing"
                 for item_id, needed in required.items()
                 if not inventory[item_id] or not inventory[item_id].is_active or inventory[item_id].quantity < needed]
    if shortages:
        raise ValueError("Insufficient inventory: " + ", ".join(shortages))
    subtotal = money(sum((money(item["unit_price"]) * int(item["quantity"]) for item in cart), Decimal(0)))
    discount = max(Decimal(0), min(money(discount), subtotal))
    tax = money((subtotal - discount) * Decimal(str(tax_rate)) / 100)
    total = money(subtotal - discount + tax)
    order_time = created_at or datetime.now(timezone.utc).replace(tzinfo=None)
    order = Order(order_number=f"TC-{order_time:%y%m%d}-{uuid4().hex[:5].upper()}",
                  client_order_id=client_order_id,
                  created_at=order_time,
                  customer_id=customer_id, order_type=order_type, status="pending",
                  subtotal=subtotal, discount=discount, tax=tax, total=total,
                  payment_method=payment_method)
    session.add(order)
    session.flush()
    for item in cart:
        quantity = int(item["quantity"])
        line_total = money(money(item["unit_price"]) * quantity)
        session.add(OrderItem(order_id=order.id, product_id=item.get("product_id"), deal_id=item.get("deal_id"),
                              quantity=quantity, unit_price=money(item["unit_price"]), total=line_total))
    session.add(Payment(order_id=order.id, amount=total, payment_method=payment_method))
    for item_id, needed in required.items():
        inventory[item_id].quantity -= needed
        session.add(InventoryMovement(inventory_item_id=item_id, order_id=order.id, user_id=user_id,
                                      quantity=-needed, movement_type="sale", notes=order.order_number))
    session.commit()
    session.refresh(order)
    return order


def dashboard_summary(session: Session) -> dict:
    start, end = business_period_bounds("Today")
    return sales_summary(session, start=start, end=end)


def order_net_total(order: Order) -> Decimal:
    """Return the amount that remains in sales after an approved cashback."""
    gross = money(order.total or 0)
    if order.cashback_status != "approved":
        return gross
    cashback = max(Decimal("0"), min(money(order.cashback_amount or 0), gross))
    return money(gross - cashback)


def sales_summary(session: Session, start: datetime | None = None,
                  end: datetime | None = None) -> dict:
    """Calculate consistent gross, cashback, net, and payment totals for a period.

    Every non-cancelled checkout is a recorded sale. Approval status remains a
    workflow status, while an approved cashback is recorded as a deduction from
    the recorded sales total.
    """
    conditions = [Order.status != "cancelled"]
    if start is not None:
        conditions.append(Order.created_at >= start)
    if end is not None:
        conditions.append(Order.created_at < end)
    orders = session.scalars(select(Order).where(*conditions)).all()
    gross = sum((money(order.total or 0) for order in orders), Decimal("0"))
    cashback = sum((money(order.cashback_amount or 0)
                    for order in orders if order.cashback_status == "approved"), Decimal("0"))
    net = sum((order_net_total(order) for order in orders), Decimal("0"))
    cash = sum((order_net_total(order) for order in orders if order.payment_method == "cash"), Decimal("0"))
    card = sum((order_net_total(order) for order in orders if order.payment_method == "card"), Decimal("0"))
    online = sum((order_net_total(order) for order in orders if order.payment_method == "online payment"), Decimal("0"))

    workflow_conditions = []
    if start is not None:
        workflow_conditions.append(Order.created_at >= start)
    if end is not None:
        workflow_conditions.append(Order.created_at < end)
    workflow_orders = session.scalars(select(Order).where(*workflow_conditions)).all()
    awaiting = sum(order.approval_status == "awaiting" for order in workflow_orders)
    pending_cashback = sum(order.cashback_status == "pending" for order in workflow_orders)

    return {
        "sales": money(net),
        "net_sales": money(net),
        "gross_sales": money(gross),
        "cashback": money(cashback),
        "orders": len(orders),
        "cash": money(cash),
        "card": money(card),
        "online": money(online),
        "awaiting": awaiting,
        "pending_cashback": pending_cashback,
        "orders_in_period": len(workflow_orders),
    }
