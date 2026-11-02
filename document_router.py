import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_student
from db.database import get_db
from db.models import CampusDocument, DocumentChunk, Student
from db.schemas import DocumentItem, DocumentUploadResponse
import document_index

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\s\.-]", "", name).strip()
    return cleaned or "document"


@router.post("", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    category: Optional[str] = Form("document"),
    department: Optional[str] = Form(None),
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Upload and index a campus document (PDF, DOCX, TXT, MD up to 10MB)."""
    raw_filename = file.filename or "uploaded_document"
    safe_filename = _sanitize_filename(raw_filename)
    extension = Path(safe_filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file format '{extension}'. Allowed: PDF, DOCX, TXT, MD.",
        )

    # Read contents and check size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds the 10 MB limit.",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot upload an empty file.",
        )

    # Determine ownership: Admins can upload public/college-wide docs, students upload private
    is_admin = getattr(current_student, "role", "student") == "admin"
    owner_id = None if is_admin else current_student.student_id
    doc_dept = department.strip() if (department and department.strip()) else (None if is_admin else current_student.department)
    doc_title = title.strip() if (title and title.strip()) else Path(safe_filename).stem.replace("_", " ").title()

    # Save to temp file for parser
    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc = document_index.ingest_file(
            db=db,
            file_path=tmp_path,
            title=doc_title,
            category=category or "document",
            department=doc_dept,
            owner_student_id=owner_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process and index document: {str(e)}",
        )
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    chunk_count = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.document_id).count()

    return DocumentUploadResponse(
        document_id=doc.document_id,
        title=doc.title,
        category=doc.category,
        department=doc.department,
        chunk_count=chunk_count,
        status="indexed",
    )


@router.get("", response_model=list[DocumentItem])
def list_documents(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """List documents visible to the current student (college-wide + department + student's private)."""
    is_admin = getattr(current_student, "role", "student") == "admin"

    if is_admin:
        docs = db.query(CampusDocument).order_by(CampusDocument.created_at.desc()).all()
    else:
        docs = (
            db.query(CampusDocument)
            .filter(
                (CampusDocument.department.is_(None)) | (CampusDocument.department == current_student.department),
                (CampusDocument.owner_student_id.is_(None)) | (CampusDocument.owner_student_id == current_student.student_id),
            )
            .order_by(CampusDocument.created_at.desc())
            .all()
        )

    results = []
    for d in docs:
        chunk_cnt = db.query(DocumentChunk).filter(DocumentChunk.document_id == d.document_id).count()
        results.append(
            DocumentItem(
                id=d.document_id,
                title=d.title,
                category=d.category,
                department=d.department,
                owner_student_id=d.owner_student_id,
                is_private=bool(d.owner_student_id),
                chunk_count=chunk_cnt,
                created_at=d.created_at,
            )
        )
    return results


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Delete a document. Students may only delete their own private documents; admins may delete any."""
    doc = db.query(CampusDocument).filter(CampusDocument.document_id == document_id).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    is_admin = getattr(current_student, "role", "student") == "admin"
    if not is_admin and doc.owner_student_id != current_student.student_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or permission denied",
        )

    # Delete from ChromaDB
    chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.document_id).all()
    chroma = document_index.get_chroma_collection()
    if chroma and chunks:
        try:
            chroma.delete(ids=[f"chunk_{c.chunk_id}" for c in chunks])
        except Exception:
            pass

    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.document_id).delete()
    db.delete(doc)
    db.commit()

    return {"status": "ok", "message": f"Document '{doc.title}' deleted successfully."}

