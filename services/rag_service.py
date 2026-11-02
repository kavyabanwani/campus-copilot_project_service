"""RAG Service providing ingest_file, ingest_document, and search."""

from document_index import (
    get_chroma_collection,
    get_embedding_model,
    ingest_document,
    ingest_file,
    recursive_split_text,
    search,
    split_into_chunks,
)

__all__ = [
    "get_embedding_model",
    "get_chroma_collection",
    "recursive_split_text",
    "split_into_chunks",
    "ingest_document",
    "ingest_file",
    "search",
]

