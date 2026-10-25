"""ChromaDB на Ubuntu 20.04 требует sqlite3 >= 3.35. Импортировать ДО chromadb."""
try:
    __import__("pysqlite3")
    import sys
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass
