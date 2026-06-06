#!/usr/bin/env python3
"""Create database tables if they do not exist."""
import sys
sys.path.insert(0, ".")

from app.db.base import Base, engine
from app.db import models  # noqa: F401 - register all models

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("✅ Veritabanı tabloları oluşturuldu.")
