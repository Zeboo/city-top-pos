from __future__ import annotations

import csv
import re
import shutil
import sys
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, QMarginsF, QSize, QSizeF, Qt, QTimer
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPixmap, QTextDocument
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QFormLayout, QGridLayout, QHBoxLayout,
    QFileDialog, QLabel, QListWidget, QListWidgetItem, QLineEdit, QMainWindow,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTabWidget, QVBoxLayout, QWidget, QDoubleSpinBox, QDateEdit,
)
from sqlalchemy import func, or_, select

from app.database import DATABASE_PATH, SessionLocal, init_db
from app.models import Category, Customer, Deal, Order, OrderItem, Product, ProductVariant, User
from app.services import authenticate, business_period_bounds, checkout, dashboard_summary, order_net_total, password_hash, sales_summary, seed_demo_menu, seed_users


# Thin-line vector icons (24x24 viewBox, stroke-only) used for the sidebar nav.
# Rendered to pixmaps at runtime so they can be recolored for the active/inactive state.
SIDEBAR_ICONS = {
    "grid": '<rect width="7" height="7" x="3" y="3" rx="1.6"/><rect width="7" height="7" x="14" y="3" rx="1.6"/>'
            '<rect width="7" height="7" x="14" y="14" rx="1.6"/><rect width="7" height="7" x="3" y="14" rx="1.6"/>',
    "circle-plus": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/><path d="M12 8v8"/>',
    "rotate": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "ticket": '<path d="M2 9a3 3 0 1 0 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 1 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/>'
              '<path d="M13 5v2"/><path d="M13 17v2"/><path d="M13 11v2"/>',
    "briefcase": '<path d="M16 20V6a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v14"/><rect width="20" height="13" x="2" y="7" rx="2"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "bar-chart": '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "settings": '<path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.2a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.2a2 2 0 0 1 1 1.7V20a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.2a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.2a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2Z"/>'
                '<circle cx="12" cy="12" r="3"/>',
    "list": '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
    "food-menu": '<path d="M6 3v7"/><path d="M3 3v4a3 3 0 0 0 6 0V3"/><path d="M6 10v11"/><path d="M15 3v18"/><path d="M15 3c3 0 5 2 5 5s-2 5-5 5"/>',
}


def render_sidebar_icon(icon_key: str, color: str, size: int = 26) -> QPixmap:
    """Renders one of SIDEBAR_ICONS as a stroke-colored pixmap at the given size."""
    body = SIDEBAR_ICONS[icon_key]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    renderer = QSvgRenderer(bytearray(svg, encoding="utf-8"))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


class WelcomeDialog(QDialog):
    def __init__(self):
        super().__init__(); self.setObjectName("welcome"); self.setWindowTitle("Decent Pizza Live"); self.setFixedSize(560, 380)
        layout = QVBoxLayout(self); layout.setContentsMargins(42, 36, 42, 36); layout.setSpacing(12)
        logo = QLabel("DECENT PIZZA LIVE"); logo.setObjectName("welcomeLogo"); logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo); title = QLabel("Welcome to Decent Pizza Live Portal"); title.setObjectName("welcomeTitle"); title.setAlignment(Qt.AlignCenter); layout.addWidget(title)
        text = QLabel("Welcome to Decent Pizza Live Portal\nYour fast, offline-first workspace for orders, sales and daily operations."); text.setObjectName("welcomeText"); text.setAlignment(Qt.AlignCenter); layout.addWidget(text); layout.addStretch()
        start = QPushButton("ENTER PORTAL  →"); start.setObjectName("welcomeButton"); start.clicked.connect(self.accept); layout.addWidget(start)


class AppMessageDialog(QDialog):
    """Consistent in-app replacement for native message boxes."""
    def __init__(self, title: str, message: str, kind: str = "info", confirm: bool = False, parent=None):
        super().__init__(parent); self.setObjectName("appMessageDialog"); self.setWindowTitle(title); self.setModal(True); self.setFixedWidth(470)
        layout = QVBoxLayout(self); layout.setContentsMargins(26, 24, 26, 22); layout.setSpacing(14)
        heading = QHBoxLayout(); icon = QLabel({"success": "✓", "warning": "!", "error": "×", "info": "i"}.get(kind, "i")); icon.setObjectName(f"messageIcon_{kind}"); icon.setAlignment(Qt.AlignCenter); heading.addWidget(icon)
        titles = QVBoxLayout(); titles.setSpacing(3); titles.addWidget(QLabel(title, objectName="messageTitle")); titles.addWidget(QLabel("Decent Pizza Live Portal", objectName="messageBrand")); heading.addLayout(titles, 1); layout.addLayout(heading)
        body = QLabel(message); body.setObjectName("messageBody"); body.setWordWrap(True); layout.addWidget(body)
        buttons = QHBoxLayout(); buttons.addStretch()
        if confirm:
            cancel = QPushButton("Cancel"); cancel.setObjectName("messageCancel"); cancel.clicked.connect(self.reject); buttons.addWidget(cancel)
            action = QPushButton("Confirm"); action.setObjectName("messageConfirm"); action.clicked.connect(self.accept); buttons.addWidget(action)
        else:
            close = QPushButton("OK"); close.setObjectName("messageConfirm"); close.clicked.connect(self.accept); buttons.addWidget(close)
        layout.addLayout(buttons)

    @classmethod
    def warning(cls, parent, title: str, message: str):
        cls(title, message, "warning", parent=parent).exec()

    @classmethod
    def info(cls, parent, title: str, message: str):
        cls(title, message, "success", parent=parent).exec()

    @classmethod
    def confirm(cls, parent, title: str, message: str) -> bool:
        return cls(title, message, "warning", confirm=True, parent=parent).exec() == QDialog.Accepted


class LoginDialog(QDialog):
    def __init__(self, session):
        super().__init__(); self.session = session; self.user = None; self.role = "cashier"; self.setObjectName("loginDialog"); self.setWindowTitle("Top City POS · Sign in"); self.setFixedSize(520, 470)
        layout = QVBoxLayout(self); layout.setContentsMargins(42, 32, 42, 32); layout.setSpacing(14)
        layout.addWidget(QLabel("TOP CITY", objectName="loginLogo")); layout.addWidget(QLabel("Sign in to your workspace", objectName="loginTitle")); layout.addWidget(QLabel("Choose your access panel to continue.", objectName="loginSubtitle"))
        panels = QHBoxLayout(); self.role_buttons = {}
        for role, label in (("cashier", "Manager / Cashier"), ("owner", "Admin / Owner")):
            button = QPushButton(label); button.setObjectName("rolePanel"); button.setCheckable(True); button.clicked.connect(lambda _, selected=role: self.select_role(selected)); self.role_buttons[role] = button; panels.addWidget(button)
        self.role_buttons["cashier"].setChecked(True); layout.addLayout(panels)
        self.username = QLineEdit(); self.username.setPlaceholderText("Username"); self.password = QLineEdit(); self.password.setPlaceholderText("Password"); self.password.setEchoMode(QLineEdit.Password); layout.addWidget(self.username); layout.addWidget(self.password)
        self.error = QLabel(""); self.error.setObjectName("loginError"); layout.addWidget(self.error)
        sign_in = QPushButton("SIGN IN"); sign_in.setObjectName("loginButton"); sign_in.clicked.connect(self.submit); layout.addWidget(sign_in); layout.addStretch(); layout.addWidget(QLabel("Offline sign-in · credentials are stored locally", objectName="loginFoot"))

    def select_role(self, role):
        self.role = role
        for name, button in self.role_buttons.items(): button.setChecked(name == role)

    def submit(self):
        user = authenticate(self.session, self.username.text(), self.password.text(), self.role)
        if not user:
            self.error.setText("Incorrect credentials for the selected panel."); return
        self.user = user; self.accept()


class StatCard(QFrame):
    def __init__(self, label: str, value: str, accent: str):
        super().__init__(); self.setObjectName("statCard")
        layout = QVBoxLayout(self); tag = QLabel(label.upper()); tag.setObjectName("muted"); amount = QLabel(value); amount.setObjectName("statValue"); amount.setStyleSheet(f"color: {accent};"); layout.addWidget(tag); layout.addWidget(amount)


class ReceiptDialog(QDialog):
    def __init__(self, order, customer, parent=None):
        super().__init__(parent); self.setObjectName("receiptDialog"); self.setWindowTitle(f"Receipt · {order.order_number}"); self.resize(480, 560)
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 22, 24, 22); layout.setSpacing(12)
        layout.addWidget(QLabel("Sale receipt", objectName="checkoutTitle")); layout.addWidget(QLabel(f"{order.order_number} · {order.order_type.title()}", objectName="checkoutSubtitle"))
        self.document = QTextDocument(self); self.document.setHtml(self.build_html(order, customer))
        preview = QLabel(); preview.setTextFormat(Qt.RichText); preview.setText(self.document.toHtml()); preview.setWordWrap(True); preview.setObjectName("receiptPreview"); layout.addWidget(preview, 1)
        buttons = QHBoxLayout(); buttons.addStretch(); ok_button = QPushButton("OK"); ok_button.setObjectName("checkoutConfirm"); ok_button.clicked.connect(self.confirm_and_print); buttons.addWidget(ok_button); layout.addLayout(buttons)

    def build_html(self, order, customer):
        receiver = f"<hr><b>Delivery receiver</b><br>{customer.name}<br>{customer.phone}<br>{customer.address}" if customer else ""
        return f"<h2 style='color:#c91f24'>DECENT PIZZA LIVE</h2><p><b>{order.order_number}</b><br>{order.order_type.title()} · {order.payment_method.title()}</p>{receiver}<hr><p>Subtotal: Rs. {order.subtotal:,.2f}<br>Discount: Rs. {order.discount:,.2f}<br>Tax: Rs. {order.tax:,.2f}<br><b>Total: Rs. {order.total:,.2f}</b></p><p>Thank you for your order.</p>"

    def print_receipt(self):
        printer = QPrinter(QPrinter.HighResolution)
        page_width_mm = 80
        page_width_points = page_width_mm * 72 / 25.4
        self.document.setDocumentMargin(2 * 72 / 25.4)
        self.document.setTextWidth(page_width_points)
        self.document.adjustSize()
        receipt_height_mm = max(50, self.document.size().height() * 25.4 / 72 + 2)
        page_size = QPageSize(QSizeF(page_width_mm, receipt_height_mm), QPageSize.Millimeter,
                              "80mm thermal receipt", QPageSize.ExactMatch)
        printer.setPageSize(page_size)
        printer.setFullPage(True)
        printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
        if not printer.isValid():
            AppMessageDialog.warning(self, "Printer unavailable", "Set the thermal printer as the Windows default printer, then try again.")
            return False
        self.document.setPageSize(QSizeF(page_width_points, receipt_height_mm * 72 / 25.4))
        self.document.print_(printer)
        return True

    def confirm_and_print(self):
        if self.print_receipt():
            self.accept()


class CheckoutDialog(QDialog):
    def __init__(self, amount: str, payment_method: str, parent=None):
        super().__init__(parent)
        self.setObjectName("checkoutDialog")
        self.setWindowTitle("Confirm checkout")
        self.setFixedSize(430, 250)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        icon = QLabel("✓"); icon.setObjectName("checkoutIcon"); icon.setAlignment(Qt.AlignCenter)
        heading.addWidget(icon)
        title = QVBoxLayout(); title.setSpacing(2)
        title.addWidget(QLabel("Confirm checkout", objectName="checkoutTitle"))
        title.addWidget(QLabel("Review the payment before saving this order.", objectName="checkoutSubtitle"))
        heading.addLayout(title, 1)
        layout.addLayout(heading)

        summary = QFrame(); summary.setObjectName("checkoutSummary"); summary_layout = QGridLayout(summary)
        summary_layout.addWidget(QLabel("Payment method", objectName="checkoutLabel"), 0, 0)
        summary_layout.addWidget(QLabel(payment_method, objectName="checkoutValue"), 0, 1, Qt.AlignRight)
        summary_layout.addWidget(QLabel("Amount due", objectName="checkoutLabel"), 1, 0)
        summary_layout.addWidget(QLabel(f"Rs. {amount}", objectName="checkoutAmount"), 1, 1, Qt.AlignRight)
        layout.addWidget(summary)

        buttons = QHBoxLayout(); buttons.setSpacing(10); buttons.addStretch()
        cancel = QPushButton("Cancel"); cancel.setObjectName("checkoutCancel"); cancel.clicked.connect(self.reject)
        confirm = QPushButton("Confirm payment"); confirm.setObjectName("checkoutConfirm"); confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel); buttons.addWidget(confirm); layout.addLayout(buttons)


class PosPage(QWidget):
    GRID_COLUMNS = 4
    CATEGORY_LABELS = {"Classic Pizzas": "Pizza", "Specialty Pizzas": "Pizza", "Sides": "Fries", "Drinks": "Drinks"}
    # Fallback icon per category, used when a product's own name doesn't match a more specific keyword below.
    CATEGORY_ICONS = {
        "Pizza": "🍕", "Burger": "🍔", "Starter": "🥗", "Fries": "🍟",
        "Sandwich": "🥪", "Shawarma": "🌯", "Roll Paratha": "🫓", "Drinks": "🥤",
    }

    def __init__(self, session, notify):
        super().__init__(); self.session, self.notify, self.cart = session, notify, []
        self.current_mode = "Takeaway"
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        header = QFrame(); header.setObjectName("orderHeader"); header.setFixedHeight(82)
        header_layout = QHBoxLayout(header); header_layout.setContentsMargins(27, 16, 27, 16); header_layout.setSpacing(18)
        brand = QVBoxLayout(); brand.setSpacing(3)
        brand.addWidget(QLabel("Decent Pizza Live", objectName="brandName"))
        brand.addWidget(QLabel("City Top Sweets & Bakers · POS", objectName="brandSub"))
        header_layout.addLayout(brand); header_layout.addSpacing(38)

        mode_bar = QFrame(); mode_bar.setObjectName("modeBar"); mode_bar.setFixedHeight(44)
        mode_layout = QHBoxLayout(mode_bar); mode_layout.setContentsMargins(4, 4, 4, 4); mode_layout.setSpacing(0)
        self.header_modes = {}
        for mode in ("Takeaway", "Delivery"):
            mode_button = QPushButton(mode); mode_button.setObjectName("modeButton"); mode_button.setCheckable(True)
            mode_button.clicked.connect(lambda _, value=mode: self.set_order_mode(value))
            self.header_modes[mode] = mode_button; mode_layout.addWidget(mode_button)
        self.header_modes["Takeaway"].setChecked(True)
        header_layout.addWidget(mode_bar, 0, Qt.AlignVCenter)
        order_label = QLabel("Order #DP-1043", objectName="headerOrder")
        header_layout.addWidget(order_label, 0, Qt.AlignVCenter)
        header_layout.addStretch()

        search_box = QFrame(); search_box.setObjectName("searchBox"); search_box.setFixedWidth(220); search_box.setFixedHeight(44)
        search_layout = QHBoxLayout(search_box); search_layout.setContentsMargins(12, 0, 10, 0); search_layout.setSpacing(6)
        search_icon = QLabel("🔍"); search_icon.setObjectName("searchIcon")
        self.search = QLineEdit(); self.search.setPlaceholderText("Search pizza, deal, burger...")
        self.search.setFrame(False); self.search.setObjectName("headerSearchInput")
        self.search.textChanged.connect(self.refresh_products)
        search_layout.addWidget(search_icon); search_layout.addWidget(self.search, 1)
        header_layout.addWidget(search_box, 0, Qt.AlignVCenter)
        self.time_label = QLabel(objectName="headerTime")
        self.update_header_clock()
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_header_clock)
        self.clock_timer.start(1000)
        header_layout.addWidget(self.time_label, 0, Qt.AlignVCenter)
        root.addWidget(header)

        content = QWidget(); content_layout = QVBoxLayout(content); content_layout.setContentsMargins(22, 16, 22, 18); content_layout.setSpacing(12)
        categories = QHBoxLayout(); self.categories = QHBoxLayout(); categories.addLayout(self.categories); categories.addStretch(); content_layout.addLayout(categories)
        size_hint = QLabel("Sizes:    S 8\"    M 11\"    L 14\"    XL 16\""); size_hint.setObjectName("sizeHint"); content_layout.addWidget(size_hint)

        body = QHBoxLayout(); body.setSpacing(18)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.host = QWidget(); self.grid = QGridLayout(self.host); self.grid.setAlignment(Qt.AlignTop); self.grid.setHorizontalSpacing(14); self.grid.setVerticalSpacing(16)
        for column in range(self.GRID_COLUMNS): self.grid.setColumnStretch(column, 1)
        scroll.setWidget(self.host); body.addWidget(scroll, 1)

        panel = QFrame(); panel.setObjectName("orderPanel"); panel.setFixedWidth(377)
        order_layout = QVBoxLayout(panel); order_layout.setContentsMargins(22, 18, 22, 18); order_layout.setSpacing(10)

        head_row = QHBoxLayout()
        head_row.addWidget(QLabel("Current order", objectName="orderHeading")); head_row.addStretch()
        self.count_badge = QLabel("0"); self.count_badge.setObjectName("countBadge"); head_row.addWidget(self.count_badge)
        order_layout.addLayout(head_row)

        self.order_number = QLabel("New order · #---"); self.order_number.setObjectName("muted"); order_layout.addWidget(self.order_number)

        self.delivery_form = QFrame(); self.delivery_form.setObjectName("deliveryForm"); form_layout = QFormLayout(self.delivery_form); form_layout.setContentsMargins(10, 8, 10, 8); form_layout.setSpacing(6)
        self.receiver_name = QLineEdit(); self.receiver_name.setPlaceholderText("Receiver name")
        self.receiver_phone = QLineEdit(); self.receiver_phone.setPlaceholderText("Phone number")
        self.receiver_address = QLineEdit(); self.receiver_address.setPlaceholderText("Delivery address")
        form_layout.addRow("Name", self.receiver_name); form_layout.addRow("Phone", self.receiver_phone); form_layout.addRow("Address", self.receiver_address); self.delivery_form.hide(); order_layout.addWidget(self.delivery_form)

        # Empty-state view (matches the design when the cart has no items yet)
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state); empty_layout.setAlignment(Qt.AlignCenter); empty_layout.setSpacing(10)
        empty_icon = QLabel("⊘"); empty_icon.setObjectName("emptyIcon"); empty_icon.setAlignment(Qt.AlignCenter)
        empty_text = QLabel("No items yet. Tap a pizza or\ndeal to start this order."); empty_text.setObjectName("emptyOrder"); empty_text.setAlignment(Qt.AlignCenter)
        empty_layout.addStretch(); empty_layout.addWidget(empty_icon); empty_layout.addWidget(empty_text); empty_layout.addStretch()
        order_layout.addWidget(self.empty_state, 1)

        # Cart contents view (shown once at least one item is added)
        self.cart_content = QWidget()
        cart_layout = QVBoxLayout(self.cart_content); cart_layout.setContentsMargins(0, 0, 0, 0); cart_layout.setSpacing(10)
        self.cart_list = QListWidget(); self.cart_list.setAlternatingRowColors(True); cart_layout.addWidget(self.cart_list, 1)

        cart_actions = QHBoxLayout()
        decrease = QPushButton("−"); decrease.setToolTip("Decrease selected item"); decrease.clicked.connect(lambda: self.adjust_selected(-1))
        increase = QPushButton("+"); increase.setToolTip("Increase selected item"); increase.clicked.connect(lambda: self.adjust_selected(1))
        remove = QPushButton("Remove"); remove.clicked.connect(self.remove_selected)
        cart_actions.addWidget(decrease); cart_actions.addWidget(increase); cart_actions.addWidget(remove); cart_layout.addLayout(cart_actions)

        summary = QFrame(); summary.setObjectName("summary"); summary_layout = QGridLayout(summary)
        summary_layout.addWidget(QLabel("SUBTOTAL", objectName="muted"), 0, 0)
        self.subtotal_label = QLabel("Rs. 0.00"); summary_layout.addWidget(self.subtotal_label, 0, 1, Qt.AlignRight)
        summary_layout.addWidget(QLabel("DISCOUNT", objectName="muted"), 1, 0)
        self.discount = QDoubleSpinBox(); self.discount.setRange(0, 100000); self.discount.setDecimals(2); self.discount.setPrefix("Rs. "); self.discount.valueChanged.connect(self.render_cart)
        summary_layout.addWidget(self.discount, 1, 1)
        summary_layout.addWidget(QLabel("TAX", objectName="muted"), 2, 0)
        self.tax_rate = QDoubleSpinBox(); self.tax_rate.setRange(0, 100); self.tax_rate.setDecimals(2); self.tax_rate.setSuffix(" %"); self.tax_rate.valueChanged.connect(self.render_cart)
        summary_layout.addWidget(self.tax_rate, 2, 1)
        summary_layout.addWidget(QLabel("TOTAL", objectName="muted"), 3, 0)
        self.total_label = QLabel("Rs. 0.00"); self.total_label.setObjectName("total"); summary_layout.addWidget(self.total_label, 3, 1, Qt.AlignRight)
        cart_layout.addWidget(summary)

        self.payment = QComboBox(); self.payment.addItems(["Cash", "Card", "Online Payment"]); cart_layout.addWidget(self.payment)
        row = QHBoxLayout(); clear = QPushButton("Clear"); clear.clicked.connect(self.clear_cart)
        pay = QPushButton("CHECKOUT"); pay.setObjectName("primary"); pay.clicked.connect(self.pay)
        row.addWidget(clear); row.addWidget(pay); cart_layout.addLayout(row)

        order_layout.addWidget(self.cart_content, 1)
        self.cart_content.hide()

        body.addWidget(panel); content_layout.addLayout(body, 1); root.addWidget(content, 1)
        self.active_category_id = None
        self.deals_button = None
        self._current_cards = []
        self.load_categories()

    def arrange_grid(self, widgets):
        self._current_cards = widgets
        while self.grid.count():
            self.grid.takeAt(0)
        for index, widget in enumerate(widgets):
            self.grid.addWidget(widget, index // self.GRID_COLUMNS, index % self.GRID_COLUMNS)

    def update_header_clock(self):
        karachi_zone = timezone(timedelta(hours=5), name="Asia/Karachi")
        self.time_label.setText(datetime.now(karachi_zone).strftime("%I:%M:%S %p"))

    def set_order_mode(self, value: str):
        self.current_mode = value
        self.sync_header_mode(value)
        self.delivery_form.setVisible(value == "Delivery")

    def sync_header_mode(self, value: str):
        for name, button in self.header_modes.items(): button.setChecked(name == value)

    def load_categories(self):
        while self.categories.count():
            item = self.categories.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        labels = self.CATEGORY_LABELS
        entries = []
        seen = set()
        for category in self.session.scalars(select(Category).where(Category.name != "Deals").order_by(Category.display_order, Category.name)):
            label = labels.get(category.name, category.name)
            if label in seen: continue
            seen.add(label); entries.append((label, category.id))
        # "Deals" always sits as the second tab, right after the first category, per the design.
        entries.insert(1 if len(entries) > 1 else len(entries), ("Deals", None))

        self.deals_button = None
        first_button = None
        first_id = None
        for tone, (label, category_id) in enumerate(entries):
            button = QPushButton(label); button.setObjectName("categoryButton"); button.setProperty("tone", str(tone % 8)); button.setCheckable(True)
            if label == "Deals":
                button.clicked.connect(self.show_deals)
                self.deals_button = button
            else:
                button.clicked.connect(lambda _, cid=category_id, b=button: self.select_category(cid, b))
                if first_button is None:
                    first_button = button; first_id = category_id
            self.categories.addWidget(button)
        if first_button is not None:
            first_button.setChecked(True)
            self.show_products(first_id)

    def select_category(self, category_id: int, button):
        for index in range(self.categories.count()):
            widget = self.categories.itemAt(index).widget()
            if widget: widget.setChecked(widget is button)
        self.show_products(category_id)

    def show_products(self, category_id: int):
        self.active_category_id = category_id
        if self.deals_button: self.deals_button.setChecked(False)
        self.refresh_products()

    def show_deals(self):
        self.active_category_id = None
        self.search.clear()
        for index in range(self.categories.count()):
            button = self.categories.itemAt(index).widget()
            if button: button.setChecked(button is self.deals_button)
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        cards = [self.build_deal_card(deal) for deal in self.session.scalars(select(Deal).where(Deal.is_active).order_by(Deal.id))]
        self.arrange_grid(cards)

    # Maps keywords found in a deal's description to a representative icon glyph + short label.
    # Ordered most-specific first so e.g. "crispy wings" matches "wing" not a more generic term.
    ITEM_ICONS = [
        ("cake", "🎂", "Cake"),
        ("pizza", "🍕", "Pizza"),
        ("shawarma", "🌯", "Shawarma"),
        ("paratha", "🫓", "Paratha"),
        ("roll", "🌯", "Roll"),
        ("sandwich", "🥪", "Sandwich"),
        ("zinger", "🍔", "Zinger"),
        ("burger", "🍔", "Burger"),
        ("wing", "🍗", "Wings"),
        ("nugget", "🍗", "Nuggets"),
        ("fries", "🍟", "Fries"),
        ("drink", "🥤", "Drink"),
        ("soda", "🥤", "Soda"),
        ("cola", "🥤", "Cola"),
        ("juice", "🧃", "Juice"),
    ]

    @classmethod
    def parse_deal_items(cls, description: str):
        """Turns a deal description like '1 Zinger, 3 Crispy Wings, 1 Itr Drink' into
        a list of (icon, short_label) tuples, one per item mentioned."""
        if not description:
            return []
        parts = re.split(r"[,+]|\band\b", description, flags=re.IGNORECASE)
        items = []
        for part in parts:
            phrase = part.strip()
            if not phrase:
                continue
            lower = phrase.lower()
            icon, label = None, None
            for keyword, emoji, nice_label in cls.ITEM_ICONS:
                if keyword in lower:
                    icon, label = emoji, nice_label
                    break
            if icon is None:
                cleaned = re.sub(r"^[\d.\sx×]+(itr|ltr|lb|pcs|pc)?\s*", "", phrase, flags=re.IGNORECASE).strip()
                icon, label = "🍽", (cleaned[:12] or phrase[:12])
            items.append((icon, label))
        return items

    @classmethod
    def resolve_product_icon(cls, name: str, category_label: str | None = None) -> str:
        """Picks a representative icon for a menu item: first tries to match a keyword in its
        own name (so 'Chicken Zinger Sandwich' still gets 🥪/🍔 correctly), then falls back to
        the category's icon, then a generic placeholder."""
        lower = (name or "").lower()
        for keyword, emoji, _ in cls.ITEM_ICONS:
            if keyword in lower:
                return emoji
        if category_label and category_label in cls.CATEGORY_ICONS:
            return cls.CATEGORY_ICONS[category_label]
        return "◎"

    def build_deal_card(self, deal: Deal):
        card = QFrame(); card.setObjectName("dealCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred); card.setMinimumWidth(200)
        layout = QVBoxLayout(card); layout.setContentsMargins(16, 14, 16, 16); layout.setSpacing(6)

        badge_row = QHBoxLayout()
        badge = QLabel("Deal"); badge.setObjectName("dealBadge")
        badge_row.addWidget(badge); badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(2)

        title_row = QHBoxLayout(); title_row.setSpacing(6)
        title = QLabel(deal.name); title.setObjectName("dealTitle"); title.setWordWrap(True)
        title_row.addWidget(title, 1)
        icon = QLabel("🏷"); icon.setObjectName("dealIcon"); icon.setFixedSize(30, 30); icon.setAlignment(Qt.AlignCenter)
        title_row.addWidget(icon, 0, Qt.AlignTop)
        layout.addLayout(title_row)

        desc = QLabel(deal.description or ""); desc.setObjectName("dealDesc"); desc.setWordWrap(True)
        layout.addWidget(desc)

        items = self.parse_deal_items(deal.description)
        if items:
            items_row = QHBoxLayout(); items_row.setSpacing(10)
            for item_icon, item_label in items:
                item_widget = QWidget()
                item_layout = QVBoxLayout(item_widget); item_layout.setContentsMargins(0, 0, 0, 0); item_layout.setSpacing(3)
                icon_badge = QLabel(item_icon); icon_badge.setObjectName("dealItemIcon"); icon_badge.setFixedSize(34, 34); icon_badge.setAlignment(Qt.AlignCenter)
                label_badge = QLabel(item_label); label_badge.setObjectName("dealItemLabel"); label_badge.setAlignment(Qt.AlignCenter)
                item_layout.addWidget(icon_badge, 0, Qt.AlignHCenter)
                item_layout.addWidget(label_badge, 0, Qt.AlignHCenter)
                items_row.addWidget(item_widget)
            items_row.addStretch()
            layout.addLayout(items_row)

        layout.addStretch()

        bottom = QHBoxLayout()
        price = QLabel(f"Rs {deal.price:,.0f}"); price.setObjectName("dealPrice")
        bottom.addWidget(price, 1)
        plus = QPushButton("+"); plus.setObjectName("plusButton"); plus.setFixedSize(30, 30); plus.setCursor(Qt.PointingHandCursor)
        plus.clicked.connect(lambda checked=False, d=deal: self.add_deal(d))
        bottom.addWidget(plus, 0, Qt.AlignRight)
        layout.addLayout(bottom)
        return card

    def add_deal(self, deal: Deal):
        for item in self.cart:
            if item.get("deal_id") == deal.id:
                item["quantity"] += 1; self.render_cart(); return
        deal_product = self.session.scalar(select(Product).where(Product.name == deal.name))
        self.cart.append({"product_id": deal_product.id if deal_product else None, "deal_id": deal.id, "name": deal.name, "unit_price": Decimal(str(deal.price)), "quantity": 1})
        self.render_cart()

    def refresh_products(self):
        if self.active_category_id is None:
            return
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        query = select(Product).where(Product.category_id == self.active_category_id, Product.is_available)
        search = self.search.text().strip()
        if search:
            query = query.where(Product.name.ilike(f"%{search}%"))
        category = self.session.get(Category, self.active_category_id)
        category_label = self.CATEGORY_LABELS.get(category.name, category.name) if category else None
        cards = []
        for product in self.session.scalars(query.order_by(Product.name)):
            variants = self.session.scalars(select(ProductVariant).where(ProductVariant.product_id == product.id, ProductVariant.is_available)).all()
            if not variants: continue
            cards.append(self.build_product_card(product, variants, category_label))
        self.arrange_grid(cards)

    def build_product_card(self, product, variants, category_label: str | None = None):
        card = QFrame(); card.setObjectName("productCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred); card.setMinimumWidth(170)
        layout = QVBoxLayout(card); layout.setContentsMargins(14, 12, 14, 12); layout.setSpacing(8)

        top = QHBoxLayout(); top.setSpacing(6)
        title = QLabel(product.name); title.setObjectName("productTitle"); title.setWordWrap(True)
        top.addWidget(title, 1)
        icon_char = self.resolve_product_icon(product.name, category_label)
        icon = QLabel(icon_char); icon.setObjectName("cardIcon"); icon.setFixedSize(30, 30); icon.setAlignment(Qt.AlignCenter)
        top.addWidget(icon, 0, Qt.AlignTop)
        layout.addLayout(top)

        desc = QLabel(product.description or "Freshly prepared"); desc.setObjectName("productDesc"); desc.setWordWrap(True)
        layout.addWidget(desc)

        chips = QHBoxLayout(); chips.setSpacing(6)
        for variant in variants:
            chip = QLabel(variant.name); chip.setObjectName("sizeChip"); chips.addWidget(chip)
        chips.addStretch()
        layout.addLayout(chips)

        bottom = QHBoxLayout()
        price = QLabel(f"Rs {min(v.price for v in variants):,.0f} onward"); price.setObjectName("price")
        bottom.addWidget(price, 1)
        plus = QPushButton("+"); plus.setObjectName("plusButton"); plus.setFixedSize(30, 30); plus.setCursor(Qt.PointingHandCursor)
        bottom.addWidget(plus, 0, Qt.AlignRight)
        layout.addLayout(bottom)

        if len(variants) > 1:
            expansion = self.build_size_picker(card, product, variants)
            layout.addWidget(expansion)
            expansion.hide()

            def toggle_expansion():
                showing = not expansion.isVisible()
                expansion.setVisible(showing)
                card.setProperty("active", showing)
                card.style().unpolish(card); card.style().polish(card)

            plus.clicked.connect(toggle_expansion)
        else:
            plus.clicked.connect(lambda checked=False, p=product, v=variants[0]: self.add_variant_to_cart(p, v))

        return card

    def build_size_picker(self, card, product, variants):
        """Builds the in-place 'choose a size' panel shown when a multi-size product's + is tapped."""
        expansion = QWidget(); expansion.setObjectName("sizeExpansion")
        exp_layout = QVBoxLayout(expansion); exp_layout.setContentsMargins(0, 10, 0, 0); exp_layout.setSpacing(10)

        size_grid = QGridLayout(); size_grid.setHorizontalSpacing(8); size_grid.setVerticalSpacing(8)
        selected = {"variant": variants[0]}
        buttons_map = {}

        def select_variant(variant):
            selected["variant"] = variant
            for v, btn in buttons_map.items():
                btn.setProperty("selected", v.id == variant.id)
                btn.style().unpolish(btn); btn.style().polish(btn)

        for index, variant in enumerate(variants):
            size_button = QPushButton(f"{variant.name}\nRs {variant.price:,.0f}")
            size_button.setObjectName("sizeOption"); size_button.setCursor(Qt.PointingHandCursor)
            size_button.setProperty("selected", index == 0)
            size_button.clicked.connect(lambda checked=False, v=variant: select_variant(v))
            buttons_map[variant] = size_button
            size_grid.addWidget(size_button, index // 2, index % 2)
        exp_layout.addLayout(size_grid)

        add_button = QPushButton("Add to order"); add_button.setObjectName("addToOrder"); add_button.setCursor(Qt.PointingHandCursor)

        def confirm_add():
            self.add_variant_to_cart(product, selected["variant"])
            expansion.hide()
            card.setProperty("active", False); card.style().unpolish(card); card.style().polish(card)

        add_button.clicked.connect(confirm_add)
        exp_layout.addWidget(add_button)
        return expansion

    def add_variant_to_cart(self, product, variant):
        for item in self.cart:
            if item.get("product_id") == product.id and item.get("variant_id") == variant.id:
                item["quantity"] += 1; self.render_cart(); return
        self.cart.append({"product_id": product.id, "variant_id": variant.id, "name": f"{product.name} · {variant.name}", "unit_price": Decimal(str(variant.price)), "quantity": 1})
        self.render_cart()

    def render_cart(self):
        self.cart_list.clear(); total = Decimal(0); item_count = 0
        for item in self.cart:
            line = Decimal(str(item["unit_price"])) * item["quantity"]; total += line; item_count += item["quantity"]
            self.cart_list.addItem(QListWidgetItem(f"{item['name']}\nQty: {item['quantity']}     Rs. {line:,.2f}"))
        discount = min(Decimal(str(self.discount.value())), total)
        tax = (total - discount) * Decimal(str(self.tax_rate.value())) / 100
        self.subtotal_label.setText(f"Rs. {total:,.2f}")
        self.total_label.setText(f"Rs. {total - discount + tax:,.2f}")
        self.count_badge.setText(str(item_count))
        has_items = bool(self.cart)
        self.empty_state.setVisible(not has_items)
        self.cart_content.setVisible(has_items)

    def adjust_selected(self, amount: int):
        row = self.cart_list.currentRow()
        if row < 0 or row >= len(self.cart): return
        self.cart[row]["quantity"] += amount
        if self.cart[row]["quantity"] <= 0: self.cart.pop(row)
        self.render_cart()

    def remove_selected(self):
        row = self.cart_list.currentRow()
        if row >= 0: self.cart.pop(row); self.render_cart()

    def clear_cart(self): self.cart.clear(); self.discount.setValue(0); self.tax_rate.setValue(0); self.render_cart()

    def pay(self):
        try:
            customer_id = None; customer = None
            if self.current_mode == "Delivery":
                name = self.receiver_name.text().strip(); phone = self.receiver_phone.text().strip(); address = self.receiver_address.text().strip()
                if not name or not phone or not address:
                    AppMessageDialog.warning(self, "Delivery details required", "Enter the receiver name, phone number, and address before checkout."); return
            dialog = CheckoutDialog(self.total_label.text()[4:], self.payment.currentText(), self)
            if dialog.exec() != QDialog.Accepted: return
            if self.current_mode == "Delivery":
                customer = Customer(name=name, phone=phone, address=address); self.session.add(customer); self.session.flush(); customer_id = customer.id
            order = checkout(self.session, self.cart, self.current_mode.lower(), self.payment.currentText().lower(), customer_id=customer_id, discount=Decimal(str(self.discount.value())), tax_rate=Decimal(str(self.tax_rate.value()))); self.clear_cart(); self.order_number.setText(f"New order · #{order.order_number}"); self.notify(f"Order {order.order_number} saved · Rs. {order.total:,.2f}"); ReceiptDialog(order, customer, self).exec()
        except ValueError as error: AppMessageDialog.warning(self, "Cannot checkout", str(error))


class DashboardPage(QWidget):
    def __init__(self, session, open_order):
        super().__init__(); self.session = session
        layout = QVBoxLayout(self); layout.setContentsMargins(32, 28, 32, 28); layout.setSpacing(10)
        layout.addWidget(QLabel("Business dashboard", objectName="pageTitle"))
        self.dashboard_subtitle = QLabel("Sales overview", objectName="subTitle"); layout.addWidget(self.dashboard_subtitle)
        filters = QHBoxLayout(); filters.addWidget(QLabel("Sales period:", objectName="muted"))
        self.period = QComboBox(); self.period.setObjectName("reportFilter"); self.period.addItems(["All dates", "Today", "Specific date", "This week", "This month"]); self.period.currentTextChanged.connect(self.refresh); filters.addWidget(self.period)
        self.selected_date = QDateEdit(QDate.currentDate()); self.selected_date.setObjectName("reportFilter"); self.selected_date.setCalendarPopup(True); self.selected_date.dateChanged.connect(self.refresh); self.selected_date.hide(); filters.addWidget(self.selected_date); filters.addStretch(); layout.addLayout(filters)
        self.stats = QHBoxLayout(); self.stats.setSpacing(15); layout.addLayout(self.stats); layout.addSpacing(18)
        panels = QHBoxLayout(); panels.setSpacing(20); panels.addWidget(self.items_panel(), 1); panels.addWidget(self.cash_panel(), 1); layout.addLayout(panels); layout.addStretch()
        action = QPushButton("＋  START NEW ORDER"); action.setObjectName("primary"); action.clicked.connect(open_order); layout.addWidget(action, 0, Qt.AlignLeft)
        self.refresh()

    def period_bounds(self):
        period = self.period.currentText()
        selected = self.selected_date.date().toPython() if period == "Specific date" else None
        start, end = business_period_bounds(period, selected)
        if period == "Specific date":
            return start, end, selected.strftime("%d %b %Y")
        return start, end, period

    def refresh(self):
        start, end, label = self.period_bounds()
        self.selected_date.setVisible(self.period.currentText() == "Specific date")
        summary = sales_summary(self.session, start, end)
        self.dashboard_subtitle.setText(f"Sales overview · {label}")
        while self.stats.count(): self.stats.takeAt(0).widget().deleteLater()
        cards = [
            ("Net sales", f"Rs. {summary['net_sales']:,.2f}", "#c91f24"),
            ("Gross sales", f"Rs. {summary['gross_sales']:,.2f}", "#99734c"),
            ("Recorded orders", str(summary["orders"]), "#3d7d4f"),
            ("Cashback deducted", f"Rs. {summary['cashback']:,.2f}", "#e7a400"),
            ("Awaiting approval", str(summary["awaiting"]), "#4d7894"),
        ]
        for label_text, value, color in cards: self.stats.addWidget(StatCard(label_text, value, color), 1)
        self.refresh_top_items(start, end)
        self.cash_label.setText(f"Cash · Rs. {summary['cash']:,.2f}")
        self.card_label.setText(f"Card · Rs. {summary['card']:,.2f}")
        self.online_label.setText(f"Online · Rs. {summary['online']:,.2f}")
        self.cashback_label.setText(f"Cashback deducted · Rs. {summary['cashback']:,.2f}")

    def items_panel(self):
        frame = QFrame(); frame.setObjectName("contentCard"); self.top_items_layout = QVBoxLayout(frame); self.top_items_layout.addWidget(QLabel("Top-selling items", objectName="cardTitle")); return frame

    def refresh_top_items(self, start, end):
        while self.top_items_layout.count() > 1:
            item = self.top_items_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                # Older dashboard instances may still contain layout-only rows.
                # Remove their child widgets as well so refresh never stacks rows.
                child_layout = item.layout()
                while child_layout.count():
                    child = child_layout.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
        conditions = [Order.status != "cancelled"]
        if start is not None: conditions.append(Order.created_at >= start)
        if end is not None: conditions.append(Order.created_at < end)
        rows = self.session.execute(select(Product.name, func.sum(OrderItem.quantity)).join(OrderItem, OrderItem.product_id == Product.id).join(Order, Order.id == OrderItem.order_id).where(*conditions).group_by(Product.name).order_by(func.sum(OrderItem.quantity).desc()).limit(5)).all()
        if not rows: rows = [("No approved sales yet", 0)]
        for n, (name, count) in enumerate(rows, 1):
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 2, 0, 2)
            rank = QLabel(str(n)); rank.setObjectName("rank"); row.addWidget(rank)
            row.addWidget(QLabel(name), 1)
            row.addWidget(QLabel(f"{int(count or 0)} sold", objectName="muted"))
            self.top_items_layout.addWidget(row_widget)

    def cash_panel(self):
        frame = QFrame(); frame.setObjectName("contentCard"); box = QVBoxLayout(frame); box.addWidget(QLabel("Payment breakdown", objectName="cardTitle")); bar = QFrame(); bar.setObjectName("cashBar"); bar.setFixedHeight(12); box.addWidget(bar)
        self.cash_label = QLabel(); self.card_label = QLabel(); self.online_label = QLabel(); self.cashback_label = QLabel()
        for label in (self.cash_label, self.card_label, self.online_label, self.cashback_label): box.addWidget(label)
        return frame


class CashbackPage(QWidget):
    def __init__(self, session, changed=None):
        super().__init__(); self.session = session; self.changed = changed
        layout = QVBoxLayout(self); layout.setContentsMargins(32, 28, 32, 28); layout.setSpacing(14)
        layout.addWidget(QLabel("Cashback", objectName="pageTitle")); layout.addWidget(QLabel("Review pending and denied sales, then keep an auditable cashback history.", objectName="subTitle"))
        self.total_card = StatCard("Cashback awaiting approval", "Rs. 0", "#c91f24"); layout.addWidget(self.total_card, 0, Qt.AlignLeft)
        self.list = QVBoxLayout(); layout.addLayout(self.list); layout.addStretch(); self.refresh()

    def refresh(self):
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        orders = self.session.scalars(select(Order).where(Order.cashback_status == "pending").order_by(Order.id.desc())).all()
        total = sum((order.cashback_amount or order.total or 0 for order in orders), Decimal(0))
        self.total_card.findChild(QLabel, "statValue").setText(f"Rs. {total:,.2f}")
        for order in orders:
            card = QFrame(); card.setObjectName("workflowCard"); row = QHBoxLayout(card)
            info = QVBoxLayout(); info.addWidget(QLabel(order.order_number, objectName="workflowTitle")); info.addWidget(QLabel(f"{order.order_type.title()} · {order.payment_method.title()} · Sale marked {order.status}", objectName="muted")); row.addLayout(info, 1)
            row.addWidget(QLabel(f"Rs. {order.cashback_amount or order.total:,.2f}", objectName="workflowAmount")); approve = QPushButton("Approve cashback"); approve.setObjectName("approveButton"); approve.clicked.connect(lambda _, oid=order.id: self.approve(oid)); row.addWidget(approve); self.list.addWidget(card)
        if not orders: self.list.addWidget(QLabel("No cashback records awaiting approval.", objectName="emptyWorkflow"))
        history_title = QLabel("Approved cashback history", objectName="cardTitle"); self.list.addWidget(history_title)
        approved = self.session.scalars(select(Order).where(Order.cashback_status == "approved").order_by(Order.id.desc()).limit(20)).all()
        for order in approved:
            card = QFrame(); card.setObjectName("workflowCard"); row = QHBoxLayout(card); info = QVBoxLayout(); info.addWidget(QLabel(order.order_number, objectName="workflowTitle")); info.addWidget(QLabel(f"{order.created_at or 'Recorded'} · Cashback approved", objectName="muted")); row.addLayout(info, 1); row.addWidget(QLabel(f"Rs. {order.cashback_amount:,.2f} deducted", objectName="workflowAmount")); status = QLabel("Approved"); status.setObjectName("statusBadge"); status.setProperty("status", "approved"); row.addWidget(status); self.list.addWidget(card)
        if not approved: self.list.addWidget(QLabel("No approved cashback records yet.", objectName="emptyWorkflow"))

    def approve(self, order_id: int):
        order = self.session.get(Order, order_id)
        if order:
            amount = order.cashback_amount or order.total or 0
            order.cashback_status = "approved"; self.session.commit(); self.refresh()
            AppMessageDialog.info(self, "Cashback approved", f"Rs. {amount:,.2f} was recorded as a cashback deduction.")
            if self.changed: self.changed()


class GuestsPage(QWidget):
    def __init__(self, session):
        super().__init__(); self.session = session
        layout = QVBoxLayout(self); layout.setContentsMargins(32, 28, 32, 28); layout.setSpacing(12)
        heading = QHBoxLayout(); title = QVBoxLayout(); title.addWidget(QLabel("Guests", objectName="pageTitle")); title.addWidget(QLabel("Keep customer details ready for delivery and repeat orders.", objectName="subTitle")); heading.addLayout(title); heading.addStretch(); self.search = QLineEdit(); self.search.setObjectName("guestSearch"); self.search.setPlaceholderText("Search guests..."); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.refresh); heading.addWidget(self.search); layout.addLayout(heading)
        columns = QHBoxLayout(); columns.setSpacing(16); layout.addLayout(columns, 1)
        form = QFrame(); form.setObjectName("menuForm"); form_layout = QFormLayout(form); form_layout.setContentsMargins(18, 18, 18, 18); form_layout.setSpacing(10); self.name = QLineEdit(); self.name.setObjectName("adminField"); self.name.setPlaceholderText("Guest name"); self.phone = QLineEdit(); self.phone.setObjectName("adminField"); self.phone.setPlaceholderText("Phone number"); self.email = QLineEdit(); self.email.setObjectName("adminField"); self.email.setPlaceholderText("Email address"); self.address = QLineEdit(); self.address.setObjectName("adminField"); self.address.setPlaceholderText("Delivery address"); form_layout.addRow("Name", self.name); form_layout.addRow("Phone", self.phone); form_layout.addRow("Email", self.email); form_layout.addRow("Address", self.address); add = QPushButton("ADD GUEST"); add.setObjectName("addMenuButton"); add.clicked.connect(self.add_guest); form_layout.addRow(add); columns.addWidget(form, 2)
        list_column = QVBoxLayout(); list_column.setSpacing(10); list_column.addWidget(QLabel("Guest directory", objectName="cardTitle")); self.list = QListWidget(); self.list.setObjectName("guestList"); self.list.setSpacing(8); list_column.addWidget(self.list, 1); columns.addLayout(list_column, 3); self.refresh()

    def add_guest(self):
        name = self.name.text().strip()
        if not name: AppMessageDialog.warning(self, "Missing name", "Enter a guest name first."); return
        self.session.add(Customer(name=name, phone=self.phone.text().strip() or None, email=self.email.text().strip() or None, address=self.address.text().strip() or None)); self.session.commit(); self.name.clear(); self.phone.clear(); self.email.clear(); self.address.clear(); self.refresh()

    def refresh(self):
        self.list.clear(); query = select(Customer).order_by(Customer.name); term = self.search.text().strip() if hasattr(self, "search") else ""
        guests = list(self.session.scalars(query))
        for guest in guests:
            if term and term.lower() not in f"{guest.name} {guest.phone or ''} {guest.email or ''}".lower(): continue
            item = QListWidgetItem(); item.setSizeHint(QSize(0, 76)); card = QFrame(); card.setObjectName("menuItemCard"); card_layout = QHBoxLayout(card); card_layout.setContentsMargins(14, 10, 14, 10); details = QVBoxLayout(); details.setSpacing(2); details.addWidget(QLabel(guest.name, objectName="menuItemName")); details.addWidget(QLabel(guest.phone or "No phone recorded", objectName="menuItemDescription")); details.addWidget(QLabel(guest.address or "No delivery address", objectName="guestAddress")); card_layout.addLayout(details, 1); badge = QLabel("GUEST"); badge.setObjectName("guestBadge"); card_layout.addWidget(badge, 0, Qt.AlignVCenter); self.list.addItem(item); self.list.setItemWidget(item, card)


class SetupPage(QWidget):
    def __init__(self, backup, database_path):
        super().__init__(); layout = QVBoxLayout(self); layout.setContentsMargins(32, 28, 32, 28); layout.setSpacing(14); layout.addWidget(QLabel("Setup", objectName="pageTitle")); layout.addWidget(QLabel("Local tools for keeping the offline POS ready.", objectName="subTitle")); card = QFrame(); card.setObjectName("contentCard"); box = QVBoxLayout(card); box.addWidget(QLabel("Database location", objectName="cardTitle")); box.addWidget(QLabel(str(database_path), objectName="pathLabel")); backup_button = QPushButton("CREATE DATABASE BACKUP"); backup_button.setObjectName("primary"); backup_button.clicked.connect(backup); box.addWidget(backup_button, 0, Qt.AlignLeft); layout.addWidget(card, 0, Qt.AlignTop); layout.addStretch()


class MenuManagerPage(QWidget):
    def __init__(self, session):
        super().__init__(); self.session = session
        layout = QVBoxLayout(self); layout.setContentsMargins(32, 28, 32, 28); layout.setSpacing(12)
        layout.addWidget(QLabel("Owner control center", objectName="pageTitle")); layout.addWidget(QLabel("Manage the menu, user access, and local POS settings.", objectName="subTitle"))
        self.tabs = QTabWidget(); self.tabs.setObjectName("adminTabs"); layout.addWidget(self.tabs, 1)
        menu_page = QWidget(); menu_layout = QVBoxLayout(menu_page); menu_layout.setContentsMargins(4, 14, 4, 4)
        menu_columns = QHBoxLayout(); menu_columns.setSpacing(16); menu_layout.addLayout(menu_columns, 1)
        form = QFrame(); form.setObjectName("menuForm"); form_layout = QFormLayout(form); form_layout.setContentsMargins(18, 18, 18, 18); form_layout.setHorizontalSpacing(18); form_layout.setVerticalSpacing(10)
        self.category = QComboBox(); self.category.setObjectName("adminField"); self.category.addItems([category.name for category in session.scalars(select(Category).where(Category.name != "Deals").order_by(Category.display_order, Category.name))]); self.name = QLineEdit(); self.name.setObjectName("adminField"); self.name.setPlaceholderText("Product name"); self.description = QLineEdit(); self.description.setObjectName("adminField"); self.description.setPlaceholderText("Short product description"); self.price = QDoubleSpinBox(); self.price.setObjectName("adminField"); self.price.setRange(0, 100000); self.price.setPrefix("Rs. "); self.price.setDecimals(2); form_layout.addRow("Category", self.category); form_layout.addRow("Name", self.name); form_layout.addRow("Description", self.description); form_layout.addRow("Price", self.price); add = QPushButton("ADD MENU ITEM"); add.setObjectName("addMenuButton"); add.clicked.connect(self.add_product); form_layout.addRow(add); menu_columns.addWidget(form, 2)
        menu_list_column = QVBoxLayout(); menu_list_column.setSpacing(10); menu_list_column.addWidget(QLabel("Current menu", objectName="cardTitle")); self.products = QListWidget(); self.products.setObjectName("menuList"); self.products.setSpacing(8); self.products.currentRowChanged.connect(self.select_product); menu_list_column.addWidget(self.products, 1); actions = QHBoxLayout(); edit = QPushButton("SAVE EDITS"); edit.setObjectName("saveMenuButton"); edit.clicked.connect(self.save_edits); remove = QPushButton("DEACTIVATE"); remove.setObjectName("denyButton"); remove.clicked.connect(self.deactivate); actions.addWidget(edit); actions.addWidget(remove); menu_list_column.addLayout(actions); menu_columns.addLayout(menu_list_column, 3); self.tabs.addTab(menu_page, "Menu & Deals")
        users_page = QWidget(); users_layout = QVBoxLayout(users_page); users_layout.setContentsMargins(4, 14, 4, 4); users_columns = QHBoxLayout(); users_columns.setSpacing(16); users_layout.addLayout(users_columns, 1); users_form_column = QVBoxLayout(); users_form_column.addWidget(QLabel("User credentials", objectName="cardTitle")); users_form = QFrame(); users_form.setObjectName("menuForm"); users_form_layout = QFormLayout(users_form); users_form_layout.setContentsMargins(18, 18, 18, 18); users_form_layout.setHorizontalSpacing(18); users_form_layout.setVerticalSpacing(10); self.user_name = QLineEdit(); self.user_name.setObjectName("adminField"); self.user_name.setPlaceholderText("Username"); self.user_password = QLineEdit(); self.user_password.setObjectName("adminField"); self.user_password.setPlaceholderText("New password"); self.user_role = QComboBox(); self.user_role.setObjectName("adminField"); self.user_role.addItems(["cashier", "owner"]); users_form_layout.addRow("Username", self.user_name); users_form_layout.addRow("Role", self.user_role); users_form_layout.addRow("Password", self.user_password); save_user = QPushButton("CREATE / RESET USER"); save_user.setObjectName("addMenuButton"); save_user.clicked.connect(self.save_user); users_form_layout.addRow(save_user); users_form_column.addWidget(users_form, 0, Qt.AlignTop); users_form_column.addStretch(); users_columns.addLayout(users_form_column, 2); users_list_column = QVBoxLayout(); users_list_column.setSpacing(10); users_list_column.addWidget(QLabel("Current users", objectName="cardTitle")); self.users = QListWidget(); self.users.setObjectName("userList"); self.users.setSpacing(8); self.users.currentRowChanged.connect(self.select_user); users_list_column.addWidget(self.users, 1); user_actions = QHBoxLayout(); toggle_user = QPushButton("TOGGLE ACTIVE"); toggle_user.setObjectName("pendingButton"); toggle_user.clicked.connect(self.toggle_user); user_actions.addWidget(toggle_user); users_list_column.addLayout(user_actions); users_columns.addLayout(users_list_column, 3); self.tabs.addTab(users_page, "Users & Roles")
        system_page = QWidget(); system_layout = QVBoxLayout(system_page); system_layout.setContentsMargins(4, 14, 4, 4); system_layout.addWidget(QLabel("System controls", objectName="cardTitle")); system_card = QFrame(); system_card.setObjectName("contentCard"); system_box = QVBoxLayout(system_card); system_box.addWidget(QLabel("Local database", objectName="workflowTitle")); system_box.addWidget(QLabel(str(DATABASE_PATH), objectName="pathLabel")); backup = QPushButton("CREATE DATABASE BACKUP"); backup.setObjectName("primary"); backup.clicked.connect(self.create_backup); system_box.addWidget(backup, 0, Qt.AlignLeft); system_layout.addWidget(system_card, 0, Qt.AlignTop); system_layout.addStretch(); self.tabs.addTab(system_page, "System")
        self.product_rows = []; self.user_rows = []; self.refresh(); self.refresh_users()

    def add_product(self):
        name = self.name.text().strip(); category = self.session.scalar(select(Category).where(Category.name == self.category.currentText()))
        if not name or not category: AppMessageDialog.warning(self, "Missing menu data", "Enter a product name and select a category."); return
        product = Product(name=name, description=self.description.text().strip() or "Freshly prepared", category_id=category.id); self.session.add(product); self.session.flush(); self.session.add(ProductVariant(product_id=product.id, name="Regular", price=self.price.value())); self.session.commit(); self.name.clear(); self.description.clear(); self.price.setValue(0); self.refresh()

    def refresh(self):
        self.products.clear()
        self.product_rows = list(self.session.scalars(select(Product).where(Product.is_available).order_by(Product.name)))
        for product in self.product_rows:
            item = QListWidgetItem(); item.setSizeHint(QSize(0, 64))
            card = QFrame(); card.setObjectName("menuItemCard"); card_layout = QHBoxLayout(card); card_layout.setContentsMargins(14, 10, 14, 10)
            details = QVBoxLayout(); details.setSpacing(2); details.addWidget(QLabel(product.name, objectName="menuItemName")); details.addWidget(QLabel(product.description or "Freshly prepared", objectName="menuItemDescription")); card_layout.addLayout(details, 1)
            variant = self.session.scalar(select(ProductVariant).where(ProductVariant.product_id == product.id).order_by(ProductVariant.id)); card_layout.addWidget(QLabel(f"Rs. {variant.price:,.0f}" if variant else "No price", objectName="menuItemPrice"), 0, Qt.AlignVCenter)
            self.products.addItem(item); self.products.setItemWidget(item, card)

    def select_product(self, row):
        if row < 0 or row >= len(self.product_rows): return
        product = self.product_rows[row]; self.name.setText(product.name); self.description.setText(product.description or "")
        variant = self.session.scalar(select(ProductVariant).where(ProductVariant.product_id == product.id).order_by(ProductVariant.id))
        if variant: self.price.setValue(float(variant.price))

    def save_edits(self):
        row = self.products.currentRow()
        if row < 0 or row >= len(self.product_rows): return
        product = self.product_rows[row]; product.name = self.name.text().strip() or product.name; product.description = self.description.text().strip() or product.description
        variant = self.session.scalar(select(ProductVariant).where(ProductVariant.product_id == product.id).order_by(ProductVariant.id))
        if variant: variant.price = self.price.value()
        self.session.commit(); self.refresh()

    def deactivate(self):
        row = self.products.currentRow()
        if row < 0 or row >= len(self.product_rows): return
        product = self.product_rows[row]
        if not AppMessageDialog.confirm(self, "Deactivate menu item", f"Remove {product.name} from the active menu?"): return
        product.is_available = False; self.session.commit(); self.refresh()

    def refresh_users(self):
        self.users.clear(); self.user_rows = list(self.session.scalars(select(User).order_by(User.role, User.username)))
        for user in self.user_rows:
            item = QListWidgetItem(); item.setSizeHint(QSize(0, 64)); card = QFrame(); card.setObjectName("menuItemCard"); card_layout = QHBoxLayout(card); card_layout.setContentsMargins(14, 10, 14, 10); details = QVBoxLayout(); details.setSpacing(2); details.addWidget(QLabel(user.username, objectName="menuItemName")); details.addWidget(QLabel(user.role.title(), objectName="menuItemDescription")); card_layout.addLayout(details, 1); status = QLabel("Active" if user.is_active else "Disabled", objectName="userStatus"); card_layout.addWidget(status, 0, Qt.AlignVCenter); self.users.addItem(item); self.users.setItemWidget(item, card)

    def select_user(self, row):
        if 0 <= row < len(self.user_rows): self.user_name.setText(self.user_rows[row].username); self.user_role.setCurrentText(self.user_rows[row].role)

    def save_user(self):
        username = self.user_name.text().strip(); password = self.user_password.text()
        if not username or not password: AppMessageDialog.warning(self, "Missing credentials", "Enter a username and password."); return
        user = self.session.scalar(select(User).where(User.username == username))
        if not user: user = User(username=username, role=self.user_role.currentText(), password_hash=password_hash(password)); self.session.add(user)
        else: user.role = self.user_role.currentText(); user.password_hash = password_hash(password); user.is_active = True
        self.session.commit(); self.user_password.clear(); self.refresh_users()

    def toggle_user(self):
        row = self.users.currentRow()
        if 0 <= row < len(self.user_rows): self.user_rows[row].is_active = not self.user_rows[row].is_active; self.session.commit(); self.refresh_users()

    def create_backup(self):
        target = DATABASE_PATH.with_name(f"top_city_backup_{datetime.now():%Y%m%d_%H%M%S}.db"); shutil.copy2(DATABASE_PATH, target); AppMessageDialog.info(self, "Backup created", f"Backup saved as {target.name}.")


class MainWindow(QMainWindow):
    def __init__(self, user):
        super().__init__(); init_db(); self.session = SessionLocal(); seed_demo_menu(self.session); self.user = user; self.is_owner = user.role == "owner"; self.setWindowTitle("Top City Bakery · Pizza POS"); self.resize(1240, 760); self.setMinimumSize(1000, 650)
        self.stack = QStackedWidget(); self.dashboard = DashboardPage(self.session, lambda: self.navigate(self.pos)); self.pos = PosPage(self.session, self.handle_order_saved); self.cashback = CashbackPage(self.session, self.handle_workflow_changed); self.orders = self.make_orders(); self.guests = GuestsPage(self.session); self.reports = self.make_reports(); self.setup = SetupPage(self.backup, DATABASE_PATH); self.menu_manager = MenuManagerPage(self.session) if self.is_owner else None; self.stack.insertWidget(0, self.dashboard); [self.stack.addWidget(page) for page in (self.pos, self.cashback, self.guests, self.setup)];
        if self.menu_manager: self.stack.addWidget(self.menu_manager)
        self.setCentralWidget(self.stack); self.build_shell(); self.refresh_dashboard()

    def handle_order_saved(self, message: str):
        self.refresh_dashboard(); self.refresh_reports(); self.load_orders(); self.statusBar().showMessage(message, 5000)

    def handle_workflow_changed(self):
        self.load_orders(); self.cashback.refresh(); self.refresh_dashboard(); self.refresh_reports()

    def refresh_application(self):
        """Reload all database-backed screens without restarting the application."""
        seed_demo_menu(self.session)
        self.pos.load_categories()
        self.pos.refresh_products()
        self.load_orders()
        self.cashback.refresh()
        self.guests.refresh()
        self.refresh_reports()
        self.refresh_dashboard()
        self.statusBar().showMessage("Application data refreshed", 3000)

    def logout(self):
        if not AppMessageDialog.confirm(self, "Sign out", "Are you sure you want to sign out of this workspace?"):
            return
        app = QApplication.instance()
        app.setQuitOnLastWindowClosed(False)
        self.close()
        login_session = SessionLocal()
        login = LoginDialog(login_session)
        if login.exec() != QDialog.Accepted:
            login_session.close()
            app.quit()
            return
        login_session.close()
        next_window = MainWindow(login.user)
        app._active_pos_window = next_window
        next_window.show()
        app.setQuitOnLastWindowClosed(True)
        self.deleteLater()

    def navigate(self, page, button=None):
        self.stack.setCurrentWidget(page)
        for side_button in self.side_buttons: side_button.setChecked(side_button is button)
        for side_button, icon_label, icon_key in self.side_icons:
            icon_label.setPixmap(render_sidebar_icon(icon_key, "#ffffff" if side_button is button else "#a98f8f"))
        if page is self.orders: self.load_orders()
        if page is self.cashback: self.cashback.refresh()
        if page is self.guests: self.guests.refresh()
        if page is self.pos: self.pos.refresh_products()
        self.refresh_dashboard()

    def build_shell(self):
        shell = QWidget(); root = QHBoxLayout(shell); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        nav = QFrame(); nav.setObjectName("sidebar"); nav.setFixedWidth(90)
        nv = QVBoxLayout(nav); nv.setContentsMargins(0, 22, 0, 18); nv.setSpacing(4)
        logo = QLabel(); logo.setObjectName("sideLogo"); logo.setAlignment(Qt.AlignCenter); logo.setFixedSize(78, 70)
        logo_path = Path(__file__).resolve().parent / "resources" / "images" / "Gemini_Generated_Image_xnd8o2xnd8o2xnd8.jpg"
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull(): logo.setPixmap(pixmap.scaled(74, 66, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        nv.addWidget(logo); nv.addSpacing(14)
        self.side_buttons = []
        self.side_icons = []  # (button, icon_label, icon_key) — used to recolor the active icon
        # Icon keys map to SIDEBAR_ICONS; order/labels match the reference layout.
        # "Menu" is the POS/menu screen. "Orders" is the order-history screen.
        # "Management" is the owner control center for menu items/users/system (formerly labeled "Menu").
        if self.is_owner:
            pages = [
                ("grid", "Home", self.dashboard),
                ("food-menu", "Menu", self.pos),
                ("rotate", "Cashback", self.cashback),
                ("ticket", "Orders", self.orders),
                ("briefcase", "Management", self.menu_manager),
                ("user", "Guests", self.guests),
                ("bar-chart", "Reports", self.reports),
            ]
        else:
            pages = [
                ("food-menu", "Menu", self.pos),
                ("rotate", "Cashback", self.cashback),
                ("ticket", "Orders", self.orders),
            ]
        for icon_key, label, page in pages:
            b = QPushButton(); b.setObjectName("sideButton"); b.setCheckable(True); b.setFixedHeight(68)
            b_layout = QVBoxLayout(b); b_layout.setContentsMargins(2, 6, 2, 4); b_layout.setSpacing(3)
            icon_label = QLabel(); icon_label.setObjectName("sideIcon"); icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setPixmap(render_sidebar_icon(icon_key, "#a98f8f"))
            icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            text_label = QLabel(label); text_label.setObjectName("sideLabel"); text_label.setAlignment(Qt.AlignCenter)
            text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            b_layout.addWidget(icon_label); b_layout.addWidget(text_label)
            b.clicked.connect(lambda _, p=page, button=b: self.navigate(p, button))
            self.side_buttons.append(b); self.side_icons.append((b, icon_label, icon_key)); nv.addWidget(b)
        nv.addStretch()
        refresh = QPushButton("↻")
        refresh.setObjectName("sideLogout")
        refresh.setToolTip("Refresh")
        refresh.setFixedHeight(42)
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refresh_application)
        nv.addWidget(refresh)
        logout = QPushButton("⎋"); logout.setObjectName("sideLogout"); logout.setFixedHeight(34); logout.setCursor(Qt.PointingHandCursor)
        logout.setToolTip("Logout")
        logout.setFixedHeight(42)
        logout.clicked.connect(self.logout)
        nv.addWidget(logout); nv.addSpacing(10)
        root.addWidget(nav); root.addWidget(self.stack, 1); self.setCentralWidget(shell); self.navigate(pages[0][2], self.side_buttons[0])

    def current_order_panel(self):
        panel = QFrame(); panel.setObjectName("currentPanel"); panel.setFixedWidth(330); box = QVBoxLayout(panel); head = QHBoxLayout(); head.addWidget(QLabel("Current order", objectName="cardTitle")); head.addStretch(); head.addWidget(QLabel("0", objectName="countBadge")); box.addLayout(head); box.addStretch(); empty = QLabel("◯\n\nNo items yet. Tap a pizza or\ndeal to start this order."); empty.setObjectName("emptyOrder"); empty.setAlignment(Qt.AlignCenter); box.addWidget(empty); box.addStretch(); go = QPushButton("START NEW ORDER"); go.setObjectName("primary"); go.clicked.connect(lambda: self.navigate(self.pos)); box.addWidget(go); return panel

    def build_topbar(self):
        bar = QFrame(); bar.setObjectName("topbar"); layout = QHBoxLayout(bar); layout.setContentsMargins(24, 12, 24, 12); logo = QLabel(f"TOP CITY  /  {self.user.role.upper()}"); logo.setObjectName("topLogo"); layout.addWidget(logo); layout.addStretch()
        for label, page in [("Menu", self.pos), ("Orders", self.orders), ("Cashback", self.cashback)] + ([("Reports", self.reports), ("Manage menu", self.menu_manager)] if self.is_owner else []):
            button = QPushButton(label); button.setObjectName("topNav"); button.clicked.connect(lambda _, p=page: self.stack.setCurrentWidget(p)); layout.addWidget(button)
        layout.addWidget(QLabel("●  Cashier", objectName="userBadge")); wrapper = QWidget(); wrapper.setLayout(QVBoxLayout()); wrapper.layout().setContentsMargins(0, 0, 0, 0); wrapper.layout().addWidget(bar); self.setMenuWidget(wrapper)

    def make_dashboard(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(30, 28, 30, 28); layout.addWidget(QLabel("Good morning, Cashier", objectName="pageTitle")); layout.addWidget(QLabel("Here is today's business overview.", objectName="muted")); self.stats = QGridLayout(); self.stats.setSpacing(16); layout.addLayout(self.stats); layout.addSpacing(20); layout.addWidget(QLabel("Quick actions", objectName="sectionTitle")); row = QHBoxLayout(); new = QPushButton("＋  New order"); new.setObjectName("actionButton"); new.clicked.connect(lambda: self.stack.setCurrentWidget(self.pos)); report = QPushButton("▣  View reports"); report.setObjectName("actionButton"); report.clicked.connect(lambda: self.stack.setCurrentWidget(self.reports)); row.addWidget(new); row.addWidget(report); row.addStretch(); layout.addLayout(row); layout.addStretch(); self.stack.addWidget(page); return page

    def refresh_dashboard(self):
        self.dashboard.refresh()

    def make_reports(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(32, 28, 32, 28); layout.setSpacing(14); heading = QHBoxLayout(); title = QVBoxLayout(); title.addWidget(QLabel("Sales reports", objectName="pageTitle")); title.addWidget(QLabel("A live view of approved and pending sales.", objectName="subTitle")); heading.addLayout(title); heading.addStretch(); self.report_filter = QComboBox(); self.report_filter.addItems(["All sales", "Awaiting approval", "Approved", "Moved to cashback"]); self.report_filter.setObjectName("reportFilter"); self.report_filter.currentTextChanged.connect(self.refresh_reports); refresh = QPushButton("Refresh"); refresh.setObjectName("refreshButton"); refresh.clicked.connect(self.refresh_reports); export = QPushButton("Export CSV"); export.setObjectName("refreshButton"); export.clicked.connect(self.export_report); heading.addWidget(self.report_filter); heading.addWidget(refresh); heading.addWidget(export); layout.addLayout(heading)
        report_dates = QHBoxLayout(); report_dates.addWidget(QLabel("Report period:", objectName="muted")); self.report_period = QComboBox(); self.report_period.setObjectName("reportFilter"); self.report_period.addItems(["All dates", "Today", "Specific date", "This week", "This month"]); self.report_period.currentTextChanged.connect(self.refresh_reports); report_dates.addWidget(self.report_period); self.report_date = QDateEdit(QDate.currentDate()); self.report_date.setObjectName("reportFilter"); self.report_date.setCalendarPopup(True); self.report_date.dateChanged.connect(self.refresh_reports); self.report_date.hide(); report_dates.addWidget(self.report_date); report_dates.addWidget(QLabel("Sort:", objectName="muted")); self.report_sort = QComboBox(); self.report_sort.setObjectName("reportFilter"); self.report_sort.addItems(["Newest first", "Oldest first", "Highest amount", "Lowest amount"]); self.report_sort.currentTextChanged.connect(self.refresh_reports); report_dates.addWidget(self.report_sort); report_dates.addStretch(); layout.addLayout(report_dates)
        self.report_stats = QHBoxLayout(); self.report_stats.setSpacing(12); layout.addLayout(self.report_stats); summary = QFrame(); summary.setObjectName("reportSummary"); summary_layout = QHBoxLayout(summary); self.report_summary = QLabel(); self.report_summary.setObjectName("reportSummaryText"); summary_layout.addWidget(self.report_summary); layout.addWidget(summary); layout.addWidget(QLabel("Sales", objectName="cardTitle")); scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); host = QWidget(); self.report_cards = QVBoxLayout(host); self.report_cards.setAlignment(Qt.AlignTop); self.report_cards.setSpacing(9); scroll.setWidget(host); layout.addWidget(scroll, 1); self.stack.addWidget(page); self.refresh_reports(); return page

    def refresh_reports(self):
        if not hasattr(self, "report_cards"): return
        period = self.report_period.currentText() if hasattr(self, "report_period") else "All dates"
        selected_date = self.report_date.date().toPython() if period == "Specific date" else None
        date_start, date_end = business_period_bounds(period, selected_date)
        self.report_date.setVisible(period == "Specific date")
        date_condition = (Order.created_at >= date_start, Order.created_at < date_end) if date_start else ()
        sort_choice = self.report_sort.currentText() if hasattr(self, "report_sort") else "Newest first"
        if sort_choice == "Oldest first":
            order_by = (Order.created_at.asc(), Order.id.asc())
        elif sort_choice == "Highest amount":
            order_by = (Order.total.desc(), Order.created_at.desc(), Order.id.desc())
        elif sort_choice == "Lowest amount":
            order_by = (Order.total.asc(), Order.created_at.desc(), Order.id.desc())
        else:
            order_by = (Order.created_at.desc(), Order.id.desc())
        orders = self.session.scalars(select(Order).where(*date_condition).order_by(*order_by)).all(); approved = [o for o in orders if o.approval_status == "approved"]; awaiting = [o for o in orders if o.approval_status == "awaiting"]; cashback = [o for o in orders if o.cashback_status == "pending"]; summary = sales_summary(self.session, date_start, date_end); selected = self.report_filter.currentText() if hasattr(self, "report_filter") else "All sales"
        if selected == "Awaiting approval": orders = awaiting
        elif selected == "Approved": orders = approved
        elif selected == "Moved to cashback": orders = cashback
        while self.report_stats.count(): self.report_stats.takeAt(0).widget().deleteLater()
        for label, value, color in [("Net sales", f"Rs. {summary['net_sales']:,.2f}", "#3d7d4f"), ("Gross sales", f"Rs. {summary['gross_sales']:,.2f}", "#99734c"), ("Cashback deducted", f"Rs. {summary['cashback']:,.2f}", "#e7a400"), ("Recorded orders", str(summary['orders']), "#c91f24"), ("Awaiting approval", str(len(awaiting)), "#4d7894")]: self.report_stats.addWidget(StatCard(label, value, color), 1)
        self.report_summary.setText(f"NET  Rs. {summary['net_sales']:,.2f}     •     APPROVED  {len(approved)}     •     AWAITING  {len(awaiting)}     •     CASHBACK QUEUE  {len(cashback)}")
        while self.report_cards.count():
            item = self.report_cards.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for order in orders[:50]:
            card = QFrame(); card.setObjectName("workflowCard"); row = QHBoxLayout(card)
            info = QVBoxLayout(); info.addWidget(QLabel(order.order_number, objectName="workflowTitle")); info.addWidget(QLabel(f"{order.order_type.title()} · {order.payment_method.title()} · {order.created_at or 'Today'}", objectName="muted")); row.addLayout(info, 1)
            status = QLabel(order.approval_status.title()); status.setObjectName("statusBadge"); status.setProperty("status", order.approval_status); row.addWidget(status)
            amount_text = f"Net Rs. {order_net_total(order):,.2f}"
            if order.cashback_status == "approved": amount_text += f"  ·  Cashback Rs. {order.cashback_amount:,.2f}"
            row.addWidget(QLabel(amount_text, objectName="workflowAmount")); self.report_cards.addWidget(card)
        if not orders: self.report_cards.addWidget(QLabel("No sales recorded today.", objectName="emptyWorkflow"))

    def export_report(self):
        period = self.report_period.currentText()
        selected = self.report_date.date().toPython() if period == "Specific date" else None
        date_start, date_end = business_period_bounds(period, selected)
        date_conditions = [Order.created_at >= date_start, Order.created_at < date_end] if date_start else []
        query = select(Order).where(*date_conditions).order_by(Order.created_at.desc(), Order.id.desc())
        orders = self.session.scalars(query).all()
        selected = self.report_filter.currentText()
        if selected == "Awaiting approval": orders = [order for order in orders if order.approval_status == "awaiting"]
        elif selected == "Approved": orders = [order for order in orders if order.approval_status == "approved"]
        elif selected == "Moved to cashback": orders = [order for order in orders if order.cashback_status == "pending"]
        default_name = f"sales_report_{now:%Y%m%d_%H%M%S}.csv"
        target, _ = QFileDialog.getSaveFileName(self, "Export sales report", str(Path.cwd() / default_name), "CSV files (*.csv)")
        if not target: return
        with open(target, "w", newline="", encoding="utf-8-sig") as report_file:
            writer = csv.writer(report_file)
            writer.writerow(["Order", "Date", "Type", "Payment", "Approval", "Cashback status", "Gross total", "Cashback deducted", "Net total"])
            for order in orders:
                deducted = order.cashback_amount if order.cashback_status == "approved" else Decimal("0")
                writer.writerow([order.order_number, order.created_at, order.order_type, order.payment_method, order.approval_status, order.cashback_status, f"{order.total or 0:.2f}", f"{deducted or 0:.2f}", f"{order_net_total(order):.2f}"])
        AppMessageDialog.info(self, "Report exported", f"Sales report saved as {Path(target).name}.")

    def make_orders(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(32, 28, 32, 28); layout.setSpacing(14)
        heading = QHBoxLayout()
        titles = QVBoxLayout(); titles.addWidget(QLabel("Order history", objectName="pageTitle")); titles.addWidget(QLabel("All saved sales remain available here after the app is closed.", objectName="subTitle")); heading.addLayout(titles, 1)
        self.order_search = QLineEdit(); self.order_search.setObjectName("guestSearch"); self.order_search.setPlaceholderText("Search order, type, or payment..."); self.order_search.setClearButtonEnabled(True); self.order_search.textChanged.connect(self.load_orders); heading.addWidget(self.order_search)
        self.order_status_filter = QComboBox(); self.order_status_filter.setObjectName("reportFilter"); self.order_status_filter.addItems(["All statuses", "Awaiting approval", "Approved", "Pending / cashback", "Denied"]); self.order_status_filter.currentTextChanged.connect(self.load_orders); heading.addWidget(self.order_status_filter)
        self.order_sort = QComboBox(); self.order_sort.setObjectName("reportFilter"); self.order_sort.addItems(["Newest first", "Oldest first", "Highest amount", "Lowest amount", "Order number A-Z"]); self.order_sort.currentTextChanged.connect(self.load_orders); heading.addWidget(self.order_sort)
        layout.addLayout(heading)
        date_filters = QHBoxLayout()
        date_filters.addWidget(QLabel("Sales period:", objectName="muted"))
        self.order_period = QComboBox(); self.order_period.setObjectName("reportFilter"); self.order_period.addItems(["All dates", "Today", "Specific date", "This week", "This month"]); self.order_period.currentTextChanged.connect(self.load_orders); date_filters.addWidget(self.order_period)
        self.order_date = QDateEdit(QDate.currentDate()); self.order_date.setObjectName("reportFilter"); self.order_date.setCalendarPopup(True); self.order_date.dateChanged.connect(self.load_orders); self.order_date.hide(); date_filters.addWidget(self.order_date)
        date_filters.addStretch(); layout.addLayout(date_filters)
        self.sales_stats = QHBoxLayout(); self.sales_stats.setSpacing(12); layout.addLayout(self.sales_stats)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); host = QWidget(); self.order_cards = QVBoxLayout(host); self.order_cards.setAlignment(Qt.AlignTop); self.order_cards.setSpacing(10); scroll.setWidget(host); layout.addWidget(scroll, 1); self.stack.addWidget(page); self.load_orders(); return page

    def load_orders(self):
        if not hasattr(self, "order_cards"): return
        while self.order_cards.count():
            item = self.order_cards.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        period = self.order_period.currentText() if hasattr(self, "order_period") else "All dates"
        selected = self.order_date.date().toPython() if period == "Specific date" else None
        date_start, date_end = business_period_bounds(period, selected)

        if hasattr(self, "order_date"): self.order_date.setVisible(period == "Specific date")
        date_condition = (Order.created_at >= date_start, Order.created_at < date_end) if date_start else ()
        all_orders = self.session.scalars(select(Order).where(*date_condition)).all()
        summary = sales_summary(self.session, date_start, date_end)
        total_sales = summary["net_sales"]
        awaiting = summary["awaiting"]
        cashback = summary["pending_cashback"]
        approved_cashback = sum((order.cashback_amount or 0 for order in all_orders if order.cashback_status == "approved"), Decimal(0))
        while self.sales_stats.count(): self.sales_stats.takeAt(0).widget().deleteLater()
        for label, value, color in [("Net sales", f"Rs. {total_sales:,.2f}", "#3d7d4f"), ("Awaiting approval", str(awaiting), "#e7a400"), ("Cashback pending", str(cashback), "#c91f24"), ("Cashback approved", f"Rs. {approved_cashback:,.2f}", "#99734c")]: self.sales_stats.addWidget(StatCard(label, value, color), 1)

        query = select(Order).where(*date_condition)
        term = self.order_search.text().strip() if hasattr(self, "order_search") else ""
        if term:
            pattern = f"%{term}%"
            query = query.where(or_(Order.order_number.ilike(pattern), Order.order_type.ilike(pattern), Order.payment_method.ilike(pattern), Order.status.ilike(pattern)))
        selected_status = self.order_status_filter.currentText() if hasattr(self, "order_status_filter") else "All statuses"
        if selected_status == "Awaiting approval":
            query = query.where(Order.approval_status == "awaiting")
        elif selected_status == "Approved":
            query = query.where(Order.approval_status == "approved")
        elif selected_status == "Pending / cashback":
            query = query.where(Order.cashback_status == "pending")
        elif selected_status == "Denied":
            query = query.where(Order.approval_status == "denied")
        sort_choice = self.order_sort.currentText() if hasattr(self, "order_sort") else "Newest first"
        if sort_choice == "Oldest first":
            query = query.order_by(Order.created_at.asc(), Order.id.asc())
        elif sort_choice == "Highest amount":
            query = query.order_by(Order.total.desc(), Order.created_at.desc(), Order.id.desc())
        elif sort_choice == "Lowest amount":
            query = query.order_by(Order.total.asc(), Order.created_at.desc(), Order.id.desc())
        elif sort_choice == "Order number A-Z":
            query = query.order_by(Order.order_number.asc())
        else:
            query = query.order_by(Order.created_at.desc(), Order.id.desc())
        orders = self.session.scalars(query).all()
        for order in orders:
            card = QFrame(); card.setObjectName("workflowCard"); row = QHBoxLayout(card)
            info = QVBoxLayout(); info.addWidget(QLabel(order.order_number, objectName="workflowTitle")); info.addWidget(QLabel(f"{order.order_type.title()} · {order.payment_method.title()} · {order.created_at or 'Today'}", objectName="muted")); row.addLayout(info, 1)
            amount_text = f"Net Rs. {order_net_total(order):,.2f}"
            if order.cashback_status == "approved": amount_text += f" · Cashback Rs. {order.cashback_amount:,.2f}"
            row.addWidget(QLabel(amount_text, objectName="workflowAmount")); status = QLabel(order.approval_status.title()); status.setObjectName("statusBadge"); status.setProperty("status", order.approval_status); row.addWidget(status)
            if order.approval_status == "awaiting":
                approve = QPushButton("Approve"); approve.setObjectName("approveButton"); approve.clicked.connect(lambda _, oid=order.id: self.set_sale_status(oid, "approved")); row.addWidget(approve)
                pending = QPushButton("Pending"); pending.setObjectName("pendingButton"); pending.clicked.connect(lambda _, oid=order.id: self.set_sale_status(oid, "pending")); row.addWidget(pending)
                deny = QPushButton("Deny"); deny.setObjectName("denyButton"); deny.clicked.connect(lambda _, oid=order.id: self.set_sale_status(oid, "denied")); row.addWidget(deny)
            self.order_cards.addWidget(card)
        if not orders: self.order_cards.addWidget(QLabel("No sales recorded yet.", objectName="emptyWorkflow"))

    def set_sale_status(self, order_id: int, status: str):
        order = self.session.get(Order, order_id)
        if not order: return
        order.approval_status = status
        if status == "approved":
            order.status = "completed"; order.cashback_status = "not_required"; order.cashback_amount = 0; order.cashback_created_at = None
        else:
            order.status = status; order.cashback_status = "pending"; order.cashback_amount = order.total; order.cashback_created_at = datetime.now()
        self.session.commit(); self.handle_workflow_changed()

    def backup(self):
        target = DATABASE_PATH.with_name(f"top_city_backup_{datetime.now():%Y%m%d_%H%M%S}.db"); shutil.copy2(DATABASE_PATH, target); self.statusBar().showMessage(f"Backup created: {target.name}", 5000)

    def closeEvent(self, event): self.session.close(); super().closeEvent(event)


STYLES = """
QWidget { color: #1a2536; font-size: 14px; } QMainWindow { background: #f5f7fb; }
QLabel { background: transparent; }
#topbar { background: #162033; min-height: 58px; } #topLogo { color: #f5b342; font-size: 18px; font-weight: 900; } #topNav { color: #dce4f0; background: transparent; border: 0; padding: 11px 18px; font-weight: 700; } #topNav:hover { color: #f5b342; } #userBadge { color: #8bd1aa; padding-left: 20px; font-weight: 700; }
#pageTitle { font-size: 29px; font-weight: 850; padding: 0; } #muted { color: #8290a4; font-size: 12px; } #sectionTitle { font-size: 14px; font-weight: 850; color: #526075; letter-spacing: 1px; }
#statCard { background: white; border: 1px solid #e3e9f2; border-radius: 14px; padding: 12px; min-height: 92px; } #statValue { font-size: 25px; font-weight: 900; }
#categoryPanel, #orderPanel { background: white; border: 1px solid #e3e9f2; border-radius: 15px; padding: 8px; } #categoryButton { text-align: left; background: transparent; border: 0; border-radius: 9px; padding: 14px 12px; font-weight: 700; color: #506078; } #categoryButton:hover { background: #fff3dc; color: #c57b08; }
#dealButton { text-align: left; background: #c91f24; color: white; border: 0; border-radius: 9px; padding: 14px 12px; font-weight: 850; } #dealButton:checked, #dealButton:hover { background: #a9161b; }
#productCard { background: white; border: 1px solid #e2e8f0; border-radius: 14px; padding: 7px; } #productCard:hover { border: 2px solid #e8a126; background: #fffaf1; } #productName { font-size: 16px; font-weight: 850; } #price { color: #d8890e; font-size: 15px; font-weight: 850; }
#dealCard { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fffefa, stop:1 #fdecbb); border: 1.5px dashed #e3b64f; border-radius: 16px; padding: 0; } #dealCard:hover { border: 1.5px dashed #c91f24; }
#dealBadge { background: #f0b429; color: #4a2e05; border: 0; border-radius: 8px; padding: 4px 12px; font-size: 11px; font-weight: 800; }
#dealTitle { font-size: 16px; font-weight: 850; color: #2b1a16; }
#dealDesc { color: #8b7e72; font-size: 12px; }
#dealIcon { background: #fbe3c8; color: #c98116; border: 0; border-radius: 15px; font-size: 13px; padding: 0; }
#dealItemIcon { background: #fbe3c8; border: 0; border-radius: 17px; font-size: 16px; padding: 0; }
#dealItemLabel { color: #8b7e72; font-size: 9px; font-weight: 750; }
#dealPrice { color: #c91f24; font-weight: 900; font-size: 16px; }
#summary { background: #f7f9fc; border-radius: 10px; } #total { color: #162033; font-size: 28px; font-weight: 900; } #primary, #actionButton { background: #e89b21; color: white; border: 0; font-weight: 850; border-radius: 9px; padding: 13px 18px; } #actionButton { background: #162033; } #actionButton:hover, #primary:hover { background: #c98116; }
QComboBox, QListWidget, QPushButton { border: 1px solid #dfe5ee; border-radius: 8px; padding: 9px; background: white; } QListWidget { padding: 4px; } #reportBox { background: white; border: 1px solid #e3e9f2; border-radius: 14px; padding: 24px; font-size: 16px; line-height: 1.5; }
#welcome { background: #162033; } #welcomeLogo { color: #f5b342; font-size: 25px; font-weight: 900; } #welcomeTitle { color: white; font-size: 25px; font-weight: 850; } #welcomeText { color: #aebbd0; font-size: 15px; } #welcomeButton { background: #e89b21; color: white; border: 0; padding: 15px; border-radius: 9px; font-weight: 850; }
#appMessageDialog { background: #fffaf3; } #messageTitle { color: #291112; font-size: 19px; font-weight: 900; } #messageBrand { color: #9a8172; font-size: 11px; } #messageBody { color: #5d4c43; font-size: 14px; line-height: 1.4; padding: 8px 2px; } #messageIcon_success, #messageIcon_warning, #messageIcon_error, #messageIcon_info { min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; border-radius: 19px; color: white; font-size: 21px; font-weight: 900; } #messageIcon_success { background: #3d7d4f; } #messageIcon_info { background: #4d7894; } #messageIcon_warning { background: #e0a21a; } #messageIcon_error { background: #c91f24; } #messageConfirm, #messageCancel { border-radius: 8px; padding: 10px 18px; font-weight: 850; } #messageConfirm { background: #c91f24; color: white; border: 0; } #messageConfirm:hover { background: #a9161b; } #messageCancel { background: transparent; color: #765f54; border: 1px solid #d9cbbb; } #messageCancel:hover { background: #f5eadb; }
"""

STYLES += """
#sidebar { background: #291112; } #sideLogo { background: #d21f24; color: #ffc20a; border: 2px solid #f6b900; border-radius: 20px; font-weight: 900; font-size: 15px; padding: 0; margin: 0 6px; min-height: 70px; max-height: 70px; qproperty-alignment: AlignCenter; } #sideButton { background: transparent; border: 0; color: #a98f8f; padding: 0; margin: 0 8px; border-radius: 12px; text-align: center; } #sideButton:hover { background: #3a1818; } #sideButton:checked { background: #d21f24; } #sideIcon { background: transparent; color: #a98f8f; font-size: 26px; padding: 0; } #sideLabel { background: transparent; color: #a98f8f; font-size: 11px; font-weight: 700; padding: 0; } #sideButton:hover #sideIcon, #sideButton:hover #sideLabel { color: #d8b8b8; } #sideButton:checked #sideIcon, #sideButton:checked #sideLabel { color: white; } #sideLogout { background: transparent; border: 0; color: #8a7373; font-size: 27px; margin: 0 18px; border-radius: 10px; } #sideLogout:hover { background: #3a1818; color: #d8b8b8; } #currentPanel { background: white; border-left: 1px solid #eadfce; } #countBadge { background: #c91f24; color: white; border-radius: 14px; padding: 5px 10px; font-weight: 900; } #contentCard { background: white; border: 1px solid #eadfce; border-radius: 16px; padding: 10px; } #cardTitle { font-size: 16px; font-weight: 850; } #rank { background: #f3ead9; color: #876f52; border-radius: 7px; padding: 5px 10px; font-weight: 900; } #cashBar { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #d21f24, stop:0.55 #d21f24, stop:0.56 #f1b000, stop:1 #f1b000); border-radius: 7px; } #emptyOrder { color: #8b7e72; font-size: 15px; } #subTitle { color: #765f54; font-size: 16px; } #topbar { background: #291112; } #cashbackResult { font-size: 20px; padding: 12px 0; } #pathLabel { color: #765f54; padding: 8px 0 18px; } #loginDialog { background: #fffaf3; } #loginLogo { color: #c91f24; font-size: 24px; font-weight: 900; letter-spacing: 2px; } #loginTitle { color: #291112; font-size: 23px; font-weight: 900; } #loginSubtitle, #loginFoot { color: #8b7e72; font-size: 12px; } #rolePanel { background: #f7ecdc; color: #765f54; border: 1px solid #eadfce; border-radius: 10px; padding: 13px 8px; font-weight: 800; } #rolePanel:checked { background: #291112; color: white; border: 2px solid #c91f24; } #loginDialog QLineEdit { background: white; border: 1px solid #dfd2c0; border-radius: 8px; padding: 11px; } #loginButton { background: #c91f24; color: white; border: 0; border-radius: 8px; padding: 12px; font-weight: 900; } #loginButton:hover { background: #a9161b; } #loginError { color: #c91f24; font-size: 12px; } #manageMenu QLineEdit { background: white; }
#orderHeader { background: white; border-bottom: 1px solid #eadfce; } #brandName { color: #c91f24; font-size: 16px; font-weight: 900; } #brandSub { color: #765f54; font-size: 11px; } #modeBar { background: #f2eadb; border-radius: 12px; } #modeButton { background: transparent; border: 0; border-radius: 9px; color: #765f54; font-weight: 800; padding: 10px 12px; min-width: 70px; } #modeButton:checked { background: #291112; color: white; } #headerOrder { font-weight: 800; padding-left: 10px; } #headerTime { color: #765f54; font-weight: 700; padding-left: 14px; } #sizeHint { color: #765f54; font-size: 12px; font-weight: 700; } #orderHeading { font-size: 16px; font-weight: 900; }
#searchBox { background: #f5f0e8; border: 0; border-radius: 12px; } #headerSearchInput { border: 0; background: transparent; padding: 9px 2px; } #searchIcon { color: #765f54; padding: 0; border: 0; background: transparent; }
#productCard { background: white; border: 1px solid #eadfce; border-radius: 16px; padding: 0; } #productCard:hover { border: 2px solid #c91f24; background: #fffaf3; }
#productTitle { font-size: 15px; font-weight: 850; color: #2b1a16; } #productDesc { color: #8b7e72; font-size: 12px; }
#sizeChip { background: #f2e9d8; color: #6c5b45; border: 0; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 700; }
#cardIcon { background: #fbe3e3; color: #c91f24; border: 0; border-radius: 15px; font-size: 15px; padding: 0; }
#price { color: #c91f24; font-weight: 900; font-size: 14px; }
#plusButton { background: #291112; color: white; border: 0; border-radius: 15px; font-weight: 900; font-size: 16px; padding: 0; }
#plusButton:hover { background: #c91f24; }
#productCard[active="true"] { border: 2px solid #c91f24; }
#sizeOption { background: #f2e9d8; border: 1px solid #eadfce; border-radius: 10px; color: #6c5b45; font-weight: 750; font-size: 12px; padding: 8px 6px; text-align: center; }
#sizeOption:hover { border: 1px solid #c91f24; }
#sizeOption[selected="true"] { background: #fff3f3; border: 2px solid #c91f24; color: #c91f24; }
#addToOrder { background: #c91f24; color: white; border: 0; border-radius: 10px; padding: 12px; font-weight: 850; font-size: 14px; }
#addToOrder:hover { background: #a9161b; }
#emptyIcon { color: #d8cbb8; font-size: 40px; border: 0; background: transparent; }
#categoryButton { background: #d5ae89; color: white; border: 0; border-radius: 10px; padding: 10px 18px; font-weight: 850; } #categoryButton:hover, #categoryButton:checked { background: #c91f24; } #categoryButton[tone="0"] { background: #c91f24; } #categoryButton[tone="1"] { background: #efc764; } #categoryButton[tone="2"] { background: #d5a27d; } #categoryButton[tone="3"] { background: #b995bd; } #categoryButton[tone="4"] { background: #e6bd63; } #categoryButton[tone="5"] { background: #91adbb; } #categoryButton[tone="6"] { background: #9db698; } #categoryButton[tone="7"] { background: #b9a58d; }
#checkoutDialog { background: #fffaf3; } #checkoutIcon { background: #c91f24; color: white; border-radius: 18px; font-size: 18px; font-weight: 900; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; } #checkoutTitle { color: #291112; font-size: 19px; font-weight: 900; } #checkoutSubtitle { color: #8b7e72; font-size: 12px; } #checkoutSummary { background: #f7ecdc; border-radius: 10px; padding: 4px 10px; } #checkoutLabel { color: #765f54; font-size: 12px; } #checkoutValue { color: #291112; font-size: 13px; font-weight: 800; } #checkoutAmount { color: #c91f24; font-size: 19px; font-weight: 900; } #checkoutCancel, #checkoutConfirm { border-radius: 8px; padding: 10px 16px; font-weight: 800; } #checkoutCancel { background: transparent; color: #765f54; border: 1px solid #d9cbbb; } #checkoutCancel:hover { background: #f5eadb; } #checkoutConfirm { background: #c91f24; color: white; border: 0; } #checkoutConfirm:hover { background: #a9161b; }
#menuList { background: transparent; border: 0; padding: 2px; } #menuList::item { background: transparent; border: 0; } #menuList::item:selected { background: transparent; } #menuItemCard { background: white; border: 1px solid #eadfce; border-radius: 12px; } #menuItemName { color: #291112; font-size: 14px; font-weight: 900; } #menuItemDescription { color: #8b7e72; font-size: 11px; } #menuItemPrice { background: #fff1cc; color: #c91f24; border-radius: 8px; padding: 8px 10px; font-size: 13px; font-weight: 900; } #menuList::item:selected #menuItemCard { border: 2px solid #c91f24; background: #fffaf3; }
#menuForm { background: #fffaf3; border: 1px solid #eadfce; border-radius: 14px; } #menuForm QLabel { color: #765f54; font-size: 12px; font-weight: 850; } #adminField { background: white; border: 1px solid #dfd2c0; border-radius: 8px; color: #291112; padding: 9px 11px; min-height: 20px; } #adminField:focus { border: 2px solid #c91f24; background: #fffdf9; } #addMenuButton, #saveMenuButton { background: #c91f24; color: white; border: 0; border-radius: 8px; padding: 11px 18px; font-size: 12px; font-weight: 900; } #addMenuButton:hover, #saveMenuButton:hover { background: #a9161b; } #saveMenuButton { background: #e7a11a; } #saveMenuButton:hover { background: #c98116; } #denyButton { background: #fbe1e1; color: #c91f24; border: 0; border-radius: 8px; padding: 11px 18px; font-size: 12px; font-weight: 900; } #denyButton:hover { background: #f3caca; }
#userList { background: transparent; border: 0; padding: 2px; } #userList::item { background: transparent; border: 0; } #userList::item:selected { background: transparent; } #userList::item:selected #menuItemCard { border: 2px solid #c91f24; background: #fffaf3; } #userStatus { background: #e2f1e4; color: #3d7d4f; border-radius: 8px; padding: 7px 10px; font-size: 11px; font-weight: 900; }
#deliveryForm { background: #f7ecdc; border: 1px solid #eadfce; border-radius: 10px; } #deliveryForm QLabel { color: #765f54; font-size: 11px; font-weight: 800; } #deliveryForm QLineEdit { background: white; border: 1px solid #dfd2c0; border-radius: 6px; padding: 6px; }
#receiptDialog { background: #fffaf3; } #receiptPreview { background: white; border: 1px solid #eadfce; border-radius: 10px; color: #291112; padding: 18px; }
#workflowCard { background: white; border: 1px solid #eadfce; border-radius: 12px; padding: 4px; } #workflowTitle { color: #291112; font-size: 14px; font-weight: 900; } #workflowAmount { color: #291112; font-size: 15px; font-weight: 900; padding: 0 12px; } #statusBadge { background: #f2eadb; color: #765f54; border-radius: 10px; padding: 6px 10px; font-size: 11px; font-weight: 800; } #statusBadge[status="approved"] { background: #e2f1e4; color: #3d7d4f; } #statusBadge[status="pending"] { background: #fff1cc; color: #9a7000; } #statusBadge[status="denied"] { background: #fbe1e1; color: #c91f24; } #approveButton, #pendingButton, #denyButton { border: 0; border-radius: 7px; padding: 8px 11px; font-size: 11px; font-weight: 800; } #approveButton { background: #3d7d4f; color: white; } #approveButton:hover { background: #2d633c; } #pendingButton { background: #fff1cc; color: #806000; } #denyButton { background: #fbe1e1; color: #c91f24; } #denyButton:hover { background: #f3caca; } #emptyWorkflow { background: white; border: 1px dashed #d9cbbb; border-radius: 12px; color: #8b7e72; padding: 22px; }
#reportSummary { background: #291112; border-radius: 12px; padding: 2px 8px; } #reportSummaryText { color: #f8e5c2; font-size: 12px; font-weight: 850; letter-spacing: 1px; padding: 8px; }
#reportFilter { background: white; border: 1px solid #dfd2c0; border-radius: 8px; padding: 8px 12px; min-width: 150px; } #refreshButton { background: #291112; color: white; border: 0; border-radius: 8px; padding: 10px 15px; font-weight: 800; } #refreshButton:hover { background: #c91f24; }
#guestSearch { background: white; border: 1px solid #dfd2c0; border-radius: 10px; padding: 10px 13px; min-width: 210px; } #guestList { background: transparent; border: 0; padding: 2px; } #guestList::item { background: transparent; border: 0; } #guestList::item:selected { background: transparent; } #guestList::item:selected #menuItemCard { border: 2px solid #c91f24; background: #fffaf3; } #guestAddress { color: #765f54; font-size: 11px; } #guestBadge { background: #fbe1e1; color: #c91f24; border-radius: 8px; padding: 7px 9px; font-size: 10px; font-weight: 900; }
#adminTabs::pane { border: 1px solid #eadfce; background: #fffaf3; border-radius: 10px; } #adminTabs QTabBar::tab { background: #f2eadb; color: #765f54; border: 0; border-radius: 8px 8px 0 0; padding: 11px 20px; margin-right: 4px; font-weight: 800; } #adminTabs QTabBar::tab:selected { background: #c91f24; color: white; } #manageMenu QLineEdit { background: white; }
"""


def main():
    init_db(); app = QApplication(sys.argv); app.setStyleSheet(STYLES)
    session = SessionLocal(); seed_users(session)
    welcome = WelcomeDialog()
    if welcome.exec() != QDialog.Accepted:
        session.close(); return
    login = LoginDialog(session)
    if login.exec() != QDialog.Accepted:
        session.close(); return
    session.close(); window = MainWindow(login.user); window.show(); sys.exit(app.exec())


if __name__ == "__main__": main()
