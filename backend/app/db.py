import typing
from sqlmodel import create_engine, Session, SQLModel, select

from app.config import settings
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

# For SQLite, we need to allow same thread if using with FastAPI
uri: str = settings.DATABASE_URL
if uri.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30}
else:
    connect_args = {}

engine = create_engine(uri, connect_args=connect_args)

def init_db() -> None:
    """
    Initialize the database by creating all defined models as tables.
    """
    import os
    from app import models
    
    # Ensure the directory for the database file exists
    if uri.startswith("sqlite:///"):
        db_path = uri.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
    SQLModel.metadata.create_all(engine)
    
    # Check for missing thumbnail column (Automatic Migration)
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        if "track" in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns("track")]
            if "thumbnail" not in columns:
                _logger.info("Migrating database: Adding 'thumbnail' column to 'track' table")
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE track ADD COLUMN thumbnail TEXT"))
    except Exception:
        _logger.exception("Automatic database migration failed")

def ensure_admin_roles() -> None:
    """
    Promote any user whose email is listed in ADMIN_EMAILS to admin on startup.
    """
    from app.config import settings
    from app.models import User

    allow = settings.admin_email_set()
    if not allow:
        return
    with Session(engine) as session:
        users = session.exec(select(User)).all()
        changed = False
        for u in users:
            if u.email.strip().lower() in allow and u.role != "admin":
                u.role = "admin"
                session.add(u)
                changed = True
        if changed:
            session.commit()


def get_session() -> typing.Generator[Session, None, None]:
    """
    Dependency generator for database sessions.

    Yields:
        A new SQLModel Session instance.
    """
    with Session(engine) as session:
        yield session
