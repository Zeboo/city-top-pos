import os
import tempfile
import unittest
from pathlib import Path


TEST_ROOT = tempfile.TemporaryDirectory(prefix="topcity-cold-drinks-")
DATABASE_FILE = Path(TEST_ROOT.name) / "report.db"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + DATABASE_FILE.as_posix()

from sqlalchemy import select
from starlette.requests import Request

from app.database import SessionLocal, engine, init_db
from app.models import Deal, OrderItem, Product, ProductVariant, User
from app.services import checkout, seed_demo_menu, seed_users
from app.web import cold_drinks_report, deal_drink_sizes


class ColdDrinksReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        with SessionLocal() as session:
            seed_users(session)
            seed_demo_menu(session)

    @classmethod
    def tearDownClass(cls):
        engine.dispose()
        TEST_ROOT.cleanup()

    def test_direct_sizes_and_deal_drinks_are_separate(self):
        with SessionLocal() as session:
            cola = session.scalar(select(Product).where(Product.name == "Coca-Cola"))
            bottle = session.scalar(select(ProductVariant).where(
                ProductVariant.product_id == cola.id, ProductVariant.name == "500ml"))
            deal = session.scalar(select(Deal).where(Deal.name == "Deal 2"))
            checkout(session, [
                {"product_id": cola.id, "variant_id": bottle.id, "unit_price": bottle.price, "quantity": 2},
                {"deal_id": deal.id, "unit_price": deal.price, "quantity": 3},
            ], "takeaway", "cash")
            saved = session.scalar(select(OrderItem).where(OrderItem.product_id == cola.id))
            self.assertEqual(saved.product_variant_id, bottle.id)
            user = session.scalar(select(User).where(User.username == "owner"))

        request = Request({"type": "http", "method": "GET", "path": "/api/cold-drinks-report",
                           "headers": [], "session": {"user_id": user.id}})
        report = cold_drinks_report(request)
        self.assertEqual(report["summary"]["direct_units"], 2)
        self.assertEqual(report["summary"]["deal_units"], 3)
        self.assertEqual(report["summary"]["total_units"], 5)
        self.assertEqual(report["direct"][0]["brand"], "Coca-Cola")
        self.assertEqual(report["direct"][0]["size"], "500ml")
        self.assertEqual(report["included_in_deals"][0]["size"], "1000ml")

    def test_deal_size_parser_normalizes_large_bottle(self):
        self.assertEqual(deal_drink_sizes("2 x 1.5 Liter Drinks"), [("1500ml", 2)])
        self.assertEqual(deal_drink_sizes("1 x 2.25 Liter Drink"), [("2200ml", 1)])
        self.assertEqual(deal_drink_sizes("1 Red Drink"), [("Unspecified", 1)])


if __name__ == "__main__":
    unittest.main()
