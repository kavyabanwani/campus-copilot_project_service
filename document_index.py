"""Campus document search (RAG for Campus Copilot).

- Embeddings: Local fastembed model (BAAI/bge-small-en-v1.5)
- Vector Store: Persistent on-disk ChromaDB collection at ./vector_store
- SQL: CampusDocument / DocumentChunk as source of truth and metadata
- Chunking: Recursive character splitting (~800 chars, ~120 overlap) per page
- Isolation: College-wide docs + student's department + student's own private uploads
"""

import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from config import settings
from db.models import CampusDocument, DocumentChunk, Student

logger = logging.getLogger("campus_copilot.rag")

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

_embedding_model: Any = None
_embedding_model_loaded = False
_chroma_collection = None


def get_embedding_model():
    """Lazily load the FastEmbed local embedding model."""
    global _embedding_model, _embedding_model_loaded

    if not _embedding_model_loaded:
        try:
            from fastembed import TextEmbedding

            _embedding_model = TextEmbedding(
                model_name=settings.EMBEDDING_MODEL
            )
            logger.info(
                "Loaded local embedding model: %s",
                settings.EMBEDDING_MODEL,
            )
        except Exception as e:
            logger.warning(
                "Could not load FastEmbed model %s: %s",
                settings.EMBEDDING_MODEL,
                e,
            )
            _embedding_model = None

        _embedding_model_loaded = True

    return _embedding_model


def get_chroma_collection(custom_path: str | None = None):
    """Get or create the persistent ChromaDB collection."""
    global _chroma_collection

    target_path = custom_path or settings.VECTOR_STORE_PATH

    if _chroma_collection is None or custom_path:
        try:
            import chromadb

            os.makedirs(target_path, exist_ok=True)
            client = chromadb.PersistentClient(path=target_path)

            collection = client.get_or_create_collection(
                name="campus_documents",
                metadata={"hnsw:space": "cosine"},
            )

            if not custom_path:
                _chroma_collection = collection

            return collection

        except Exception as e:
            logger.warning(
                "Could not initialize ChromaDB at %s: %s",
                target_path,
                e,
            )
            return None

    return _chroma_collection


def recursive_split_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split text recursively by paragraphs, sentences, and spaces with overlap."""
    text = text.strip()

    if not text:
        return []

    separators = ["\n\n", "\n", ". ", "; ", ", ", " "]

    def _split_recursive(
        text_to_split: str,
        seps: list[str],
    ) -> list[str]:

        if len(text_to_split) <= chunk_size:
            return [text_to_split] if text_to_split.strip() else []

        sep = seps[0] if seps else ""
        next_seps = seps[1:] if len(seps) > 1 else []

        if sep and sep in text_to_split:
            parts = text_to_split.split(sep)
        else:
            if next_seps:
                return _split_recursive(text_to_split, next_seps)

            step = max(1, chunk_size - chunk_overlap)

            parts = [
                text_to_split[i:i + chunk_size]
                for i in range(0, len(text_to_split), step)
            ]

            return [p.strip() for p in parts if p.strip()]

        chunks = []
        current = ""

        for part in parts:
            candidate = f"{current}{sep}{part}" if current else part

            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current.strip():
                    chunks.append(current.strip())

                if len(part) > chunk_size and next_seps:
                    sub_chunks = _split_recursive(part, next_seps)
                    chunks.extend(sub_chunks)
                    current = ""
                else:
                    current = part

        if current.strip():
            chunks.append(current.strip())

        overlapped = []

        for i, chunk in enumerate(chunks):
            if i > 0 and chunk_overlap > 0:
                prev_tail = chunks[i - 1][-chunk_overlap:]
                combined = f"{prev_tail} {chunk}".strip()
                overlapped.append(combined[:chunk_size])
            else:
                overlapped.append(chunk)

        return overlapped or [text_to_split]

    return _split_recursive(text, separators)


def split_into_chunks(raw_text: str) -> list[str]:
    """Compatibility method for legacy callers."""
    return recursive_split_text(raw_text)


def _embed_texts(texts: list[str]) -> list[list[float]] | None:
    model = get_embedding_model()

    if not model or not texts:
        return None

    try:
        embeddings = list(model.embed(texts))

        return [
            e.tolist() if hasattr(e, "tolist") else list(e)
            for e in embeddings
        ]

    except Exception as e:
        logger.warning("Error computing embeddings: %s", e)
        return None


def _keyword_score(query: str, content: str) -> float:
    """Keyword overlap fallback, matching numbers and alphanumeric tokens."""
    query_tokens = {
        w.lower()
        for w in re.findall(r"[a-zA-Z0-9]{2,}", query)
    }

    if not query_tokens:
        return 0.0

    content_tokens = {
        w.lower()
        for w in re.findall(r"[a-zA-Z0-9]{2,}", content)
    }

    overlap = len(query_tokens & content_tokens)

    return overlap / len(query_tokens)


def _cosine_similarity(
    left: list[float],
    right: list[float],
) -> float:

    dot = sum(a * b for a, b in zip(left, right))
    left_size = math.sqrt(sum(a * a for a in left))
    right_size = math.sqrt(sum(b * b for b in right))

    if not left_size or not right_size:
        return 0.0

    return dot / (left_size * right_size)


def ingest_document(
    db: Session,
    title: str,
    category: str,
    raw_text: str,
    department: str | None = None,
    owner_student_id: int | None = None,
    pages_data: list[tuple[int, str]] | None = None,
) -> CampusDocument:
    """Store a document and its embedded chunks in SQL and ChromaDB."""

    existing = (
        db.query(CampusDocument)
        .filter(CampusDocument.title == title)
        .first()
    )

    chroma = get_chroma_collection()

    if existing:
        old_chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.document_id == existing.document_id
            )
            .all()
        )

        if chroma and old_chunks:
            try:
                chroma.delete(
                    ids=[f"chunk_{c.chunk_id}" for c in old_chunks]
                )
            except Exception as e:
                logger.debug("Chroma delete warning: %s", e)

        (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.document_id == existing.document_id
            )
            .delete()
        )

        document = existing
        document.category = category
        document.department = department
        document.owner_student_id = owner_student_id

    else:
        document = CampusDocument(
            title=title,
            category=category,
            department=department,
            owner_student_id=owner_student_id,
        )

        db.add(document)
        db.flush()

    chunk_items: list[tuple[int, str]] = []

    if pages_data:
        for page_num, page_content in pages_data:
            page_chunks = recursive_split_text(page_content)

            for chunk in page_chunks:
                chunk_items.append((page_num, chunk))

    else:
        raw_chunks = recursive_split_text(raw_text)

        for chunk in raw_chunks:
            chunk_items.append((1, chunk))

    if not chunk_items and raw_text.strip():
        chunk_items.append((1, raw_text.strip()))

    texts = [chunk[1] for chunk in chunk_items]
    embeddings = _embed_texts(texts)

    db_chunks = []

    for i, (page_num, chunk_text) in enumerate(chunk_items):
        emb_json = (
            json.dumps(embeddings[i])
            if embeddings and i < len(embeddings)
            else None
        )

        db_chunk = DocumentChunk(
            document_id=document.document_id,
            page_number=page_num,
            content=chunk_text,
            embedding=emb_json,
        )

        db.add(db_chunk)
        db_chunks.append(db_chunk)

    db.commit()

    for chunk in db_chunks:
        db.refresh(chunk)

    db.refresh(document)

    if chroma and embeddings and len(embeddings) == len(db_chunks):
        try:
            ids = [
                f"chunk_{chunk.chunk_id}"
                for chunk in db_chunks
            ]

            metadatas = [
                {
                    "document_id": document.document_id,
                    "title": document.title,
                    "category": document.category,
                    "department": document.department or "",
                    "owner_student_id": document.owner_student_id or 0,
                    "page_number": chunk.page_number or 1,
                    "chunk_id": chunk.chunk_id,
                }
                for chunk in db_chunks
            ]

            chroma.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )

        except Exception as e:
            logger.warning("Error saving to ChromaDB: %s", e)

    return document


def ingest_file(
    db: Session,
    file_path: str | Path,
    title: str,
    category: str = "document",
    department: str | None = None,
    owner_student_id: int | None = None,
) -> CampusDocument:
    """Ingest a file (PDF, DOCX, TXT, MD) with real page numbers."""

    path = Path(file_path)
    extension = path.suffix.lower()

    pages_data: list[tuple[int, str]] = []
    full_text = ""

    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))

        for page_idx, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()

            if text:
                pages_data.append((page_idx + 1, text))
                full_text += f"\n\n{text}"

    elif extension == ".docx":
        import docx

        doc = docx.Document(str(path))
        paras = [
            p.text.strip()
            for p in doc.paragraphs
            if p.text.strip()
        ]

        full_text = "\n\n".join(paras)
        pages_data = [(1, full_text)]

    else:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            full_text = f.read()

        pages_data = [(1, full_text)]

    return ingest_document(
        db=db,
        title=title,
        category=category,
        raw_text=full_text,
        department=department,
        owner_student_id=owner_student_id,
        pages_data=pages_data,
    )


def search_documents(
    db: Session,
    query: str,
    student: Student | None = None,
    department: str | None = None,
    top_k: int = 4,
) -> list[dict]:
    """Semantic search over campus documents with student isolation."""

    target_dept = department or (
        student.department if student else None
    )

    target_owner_id = student.student_id if student else None

    doc_query = (
        db.query(DocumentChunk, CampusDocument)
        .join(
            CampusDocument,
            CampusDocument.document_id == DocumentChunk.document_id,
        )
    )

    if student:
        dept_filter = (
            (CampusDocument.department.is_(None))
            | (CampusDocument.department == target_dept)
        )

        owner_filter = (
            (CampusDocument.owner_student_id.is_(None))
            | (CampusDocument.owner_student_id == target_owner_id)
        )

        doc_query = doc_query.filter(dept_filter, owner_filter)

    elif target_dept:
        doc_query = doc_query.filter(
            (
                CampusDocument.department.is_(None)
            ) | (
                CampusDocument.department == target_dept
            ),
            CampusDocument.owner_student_id.is_(None),
        )

    else:
        doc_query = doc_query.filter(
            CampusDocument.department.is_(None),
            CampusDocument.owner_student_id.is_(None),
        )

    rows = doc_query.all()

    if not rows:
        return []

    chroma = get_chroma_collection()
    model = get_embedding_model()

    if chroma and model:
        try:
            query_emb = list(model.embed([query]))[0]

            query_vector = (
                query_emb.tolist()
                if hasattr(query_emb, "tolist")
                else list(query_emb)
            )

            results = chroma.query(
                query_embeddings=[query_vector],
                n_results=min(top_k * 4, 30),
            )

            scored = []

            allowed_chunk_ids = {
                chunk.chunk_id for chunk, _ in rows
            }

            row_map = {
                chunk.chunk_id: (chunk, document)
                for chunk, document in rows
            }

            if results and results.get("ids") and results["ids"][0]:
                for idx, cid_str in enumerate(results["ids"][0]):
                    try:
                        cid = int(cid_str.replace("chunk_", ""))
                    except ValueError:
                        continue

                    if cid in allowed_chunk_ids:
                        chunk, document = row_map[cid]

                        dist = (
                            results["distances"][0][idx]
                            if results.get("distances")
                            else 0.5
                        )

                        similarity = max(
                            0.0,
                            min(1.0, 1.0 - dist),
                        )

                        scored.append(
                            (similarity, chunk, document)
                        )

                if scored:
                    scored.sort(
                        key=lambda item: item[0],
                        reverse=True,
                    )

                    return [
                        {
                            "content": chunk.content,
                            "title": document.title,
                            "category": document.category,
                            "page": chunk.page_number or 1,
                            "score": round(score, 4),
                            "snippet": (
                                chunk.content[:220].strip()
                                + (
                                    "..."
                                    if len(chunk.content) > 220
                                    else ""
                                )
                            ),
                        }
                        for score, chunk, document in scored[:top_k]
                        if score > 0.15
                    ]

        except Exception as e:
            logger.warning(
                "Chroma query failed, using SQL/keyword fallback: %s",
                e,
            )

    logger.info(
        "Using SQL cosine / keyword fallback for document search"
    )

    query_emb = None

    if model:
        try:
            raw_emb = list(model.embed([query]))[0]

            query_emb = (
                raw_emb.tolist()
                if hasattr(raw_emb, "tolist")
                else list(raw_emb)
            )

        except Exception:
            query_emb = None

    scored_sql = []

    for chunk, document in rows:
        if query_emb and chunk.embedding:
            try:
                emb_vec = json.loads(chunk.embedding)
                score = _cosine_similarity(query_emb, emb_vec)

            except Exception:
                score = _keyword_score(query, chunk.content)

        else:
            score = _keyword_score(query, chunk.content)

        scored_sql.append((score, chunk, document))

    scored_sql.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return [
        {
            "content": chunk.content,
            "title": document.title,
            "category": document.category,
            "page": chunk.page_number or 1,
            "score": round(score, 4),
            "snippet": (
                chunk.content[:220].strip()
                + (
                    "..."
                    if len(chunk.content) > 220
                    else ""
                )
            ),
        }
        for score, chunk, document in scored_sql[:top_k]
        if score > 0.05
    ]


search = search_documents
    