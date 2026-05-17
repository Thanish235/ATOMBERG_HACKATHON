from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from models import Base
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./atomquest.db")

# Render mounts persistent storage at /var/data; use DB_DIR to point there
if DATABASE_URL.startswith("sqlite"):
    db_dir = os.environ.get("DB_DIR", ".")
    db_path = os.path.join(db_dir, "atomquest.db")
    DATABASE_URL = f"sqlite:///{db_path}"
    os.makedirs(db_dir, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    # If the schema has new tables, wipe and recreate so seed data loads correctly.
    # Fine for hackathon/dev; swap for Alembic migrations before prod.
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    required = set(Base.metadata.tables.keys())
    missing = required - existing

    if missing:
        print(f"Schema out of date — missing tables: {missing}. Recreating...")
        Base.metadata.drop_all(bind=engine)

    Base.metadata.create_all(bind=engine)
    print("Database ready")
