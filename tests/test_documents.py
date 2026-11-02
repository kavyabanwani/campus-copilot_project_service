import io
from fastapi import status
import document_index
from services.rag_service import search


def test_document_upload_and_chunking(client, auth_headers_admin, auth_headers_a, db):
    # Upload multi-page text document as admin
    doc_content = (
        "Page 1: Introduction to Department Syllabus and Lab Guidelines.\n"
        "Students must follow strict safety procedures in the computer lab.\n\n"
        "Page 2: Minimum attendance requirement for laboratory sessions is mandatory.\n"
        "Students missing more than 2 lab experiments must attend make-up sessions."
    )
    file_bytes = io.BytesIO(doc_content.encode("utf-8"))

    res = client.post(
        "/api/documents",
        files={"file": ("lab_guidelines.txt", file_bytes, "text/plain")},
        data={"title": "Computer Lab Guidelines", "category": "syllabus"},
        headers=auth_headers_admin,
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["title"] == "Computer Lab Guidelines"
    assert data["chunk_count"] >= 1
    assert data["status"] == "indexed"


def test_document_size_and_extension_rejections(client, auth_headers_a):
    # Wrong extension (.exe)
    bad_file = io.BytesIO(b"binary data")
    res_bad = client.post(
        "/api/documents",
        files={"file": ("malware.exe", bad_file, "application/octet-stream")},
        headers=auth_headers_a,
    )
    assert res_bad.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Oversized file (>10 MB)
    large_file = io.BytesIO(b"A" * (10 * 1024 * 1024 + 100))
    res_large = client.post(
        "/api/documents",
        files={"file": ("huge_document.txt", large_file, "text/plain")},
        headers=auth_headers_a,
    )
    assert res_large.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


def test_retrieval_minimum_attendance_requirement(db, student_a, monkeypatch):
    monkeypatch.setattr(document_index, "get_chroma_collection", lambda: None)
    monkeypatch.setattr(document_index, "get_embedding_model", lambda: None)

    results = search(
        db,
        "75 percent attendance",
        student=student_a,
        top_k=2,
    )
    policy = next(
        (result for result in results if result["title"] == "Academic Attendance Policy"),
        None,
    )
    assert policy is not None
    assert policy["page"] == 1
    assert "75 percent attendance" in policy["content"]
