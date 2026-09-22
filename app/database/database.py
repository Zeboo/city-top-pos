from collections.abc import Generator
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "top_city.db"
_configured_database_url = os.getenv("DATABASE_URL", "").strip()
if _configured_database_url:
    # Railway commonly provides postgresql://; psycopg is the SQLAlchemy 2 driver.
    DATABASE_URL = _configured_database_url.replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
else:
    DATABASE_URL = f"sqlite+pysqlite:///{DATABASE_PATH.as_posix()}"


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    from app.models import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # create_all intentionally does not alter existing SQLite tables. Keep the
    # starter database compatible when the blueprint adds a small new field.
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(categories)"))}
            if "display_order" not in columns:
                connection.execute(text("ALTER TABLE categories ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0"))
            deal_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(deals)"))}
            if "price" not in deal_columns:
                connection.execute(text("ALTER TABLE deals ADD COLUMN price NUMERIC(10, 2) NOT NULL DEFAULT 0"))
            order_item_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(order_items)"))}
            if "deal_id" not in order_item_columns:
                connection.execute(text("ALTER TABLE order_items ADD COLUMN deal_id INTEGER"))
            order_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(orders)"))}
            if "client_order_id" not in order_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN client_order_id VARCHAR(36)"))
            if "approval_status" not in order_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN approval_status VARCHAR(30) NOT NULL DEFAULT 'awaiting'"))
            if "cashback_status" not in order_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN cashback_status VARCHAR(30) NOT NULL DEFAULT 'not_required'"))
            if "cashback_amount" not in order_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN cashback_amount NUMERIC(10, 2) NOT NULL DEFAULT 0"))
            if "cashback_created_at" not in order_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN cashback_created_at DATETIME"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_orders_client_order_id ON orders (client_order_id)"))
    elif engine.dialect.name == "postgresql":
        # create_all does not evolve an existing production table. Add the
        # offline-sync idempotency key without recreating production data.
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_order_id VARCHAR(36)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_orders_client_order_id ON orders (client_order_id)"))
