"""Rebuild the FAISS index from embeddings stored in the database: ``python -m backend.scripts.reindex``."""
from backend.core.logging import configure_logging
from backend.db.session import init_db
from backend.services.vector_store import knowledge_index

if __name__ == "__main__":
    configure_logging(as_json=False)
    init_db()
    print(f"{knowledge_index.rebuild()} vectors indexed")
