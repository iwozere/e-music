import typing
from sqlalchemy import event
from sqlmodel import col, create_engine, Session, SQLModel, select

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

if uri.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _):  # type: ignore[misc]
        """Enable WAL mode for concurrent read/write without full table locks."""
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")

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

def ensure_admin_roles() -> None:
    """Promote users listed in ADMIN_EMAILS to admin on startup (targeted query, not full scan)."""
    from app.models import User

    allow = settings.admin_email_set()
    if not allow:
        return
    with Session(engine) as session:
        stmt = select(User).where(col(User.email).in_(list(allow)))
        changed = False
        for u in session.exec(stmt).all():
            if u.role != "admin":
                u.role = "admin"
                session.add(u)
                changed = True
        if changed:
            session.commit()


def get_session() -> typing.Generator[Session, None, None]:
    """Dependency generator for database sessions with automatic rollback on error."""
    with Session(engine) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
