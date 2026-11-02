from fastapi import status
from db.models import ChatMessage, ChatSession, CampusDocument, DocumentChunk


def test_student_cannot_read_or_delete_other_student_chat_sessions(
    client, auth_headers_a, auth_headers_b, student_b, db
):
    # Create session for Student B
    session_b = ChatSession(student_id=student_b.student_id, title="Bob's Private Question")
    db.add(session_b)
    db.commit()
    db.refresh(session_b)

    msg = ChatMessage(session_id=session_b.id, role="user", content="Secret personal query")
    db.add(msg)
    db.commit()

    # Student A tries to read Student B's session -> must be 404
    res = client.get(f"/chat/sessions/{session_b.id}", headers=auth_headers_a)
    assert res.status_code == status.HTTP_404_NOT_FOUND

    # Student A tries to delete Student B's session -> must be 404
    del_res = client.delete(f"/chat/sessions/{session_b.id}", headers=auth_headers_a)
    assert del_res.status_code == status.HTTP_404_NOT_FOUND

    # Student B CAN read their own session
    bob_res = client.get(f"/chat/sessions/{session_b.id}", headers=auth_headers_b)
    assert bob_res.status_code == status.HTTP_200_OK
    assert bob_res.json()["title"] == "Bob's Private Question"


def test_student_cannot_see_other_student_private_documents(
    client, auth_headers_a, auth_headers_b, student_b, db
):
    # Create private document for Student B
    private_doc = CampusDocument(
        title="Bob's Medical Leave Certificate",
        category="medical",
        department="Computer Science",
        owner_student_id=student_b.student_id,
    )
    db.add(private_doc)
    db.flush()
    db.add(DocumentChunk(document_id=private_doc.document_id, page_number=1, content="Personal medical diagnosis"))
    db.commit()

    # Student A lists documents -> private_doc must NOT appear
    res_a = client.get("/api/documents", headers=auth_headers_a)
    assert res_a.status_code == status.HTTP_200_OK
    titles_a = [d["title"] for d in res_a.json()]
    assert "Bob's Medical Leave Certificate" not in titles_a

    # Student A tries to delete Student B's doc -> 404
    del_res = client.delete(f"/api/documents/{private_doc.document_id}", headers=auth_headers_a)
    assert del_res.status_code == status.HTTP_404_NOT_FOUND

    # Student B lists documents -> private_doc DOES appear
    res_b = client.get("/api/documents", headers=auth_headers_b)
    assert res_b.status_code == status.HTTP_200_OK
    titles_b = [d["title"] for d in res_b.json()]
    assert "Bob's Medical Leave Certificate" in titles_b

