from fastapi import status
from llm_client import ModelReply


def test_chat_history_persistence_and_followup(monkeypatch, client, auth_headers_a):
    replies = [
        ModelReply(text="You have 4 subjects this term: DBMS, OS, AI, and Discrete Math."),
        ModelReply(text="DBMS has the lowest attendance at 72%."),
    ]

    def mock_chat(system_instruction, messages, tools):
        return replies.pop(0)

    monkeypatch.setattr("llm_client.chat", mock_chat)

    # First question
    res1 = client.post(
        "/ai/chat",
        json={"message": "What subjects do I have?"},
        headers=auth_headers_a,
    )
    assert res1.status_code == status.HTTP_200_OK
    data1 = res1.json()
    assert "You have 4 subjects" in data1["content"]
    session_id = data1["session_id"]
    assert session_id is not None

    # Follow-up question using session_id
    res2 = client.post(
        "/ai/chat",
        json={"message": "Which one is lowest?", "session_id": session_id},
        headers=auth_headers_a,
    )
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()["session_id"] == session_id
    assert "DBMS has the lowest" in res2.json()["content"]

    # Verify session detail returns both user & assistant messages
    detail_res = client.get(f"/chat/sessions/{session_id}", headers=auth_headers_a)
    assert detail_res.status_code == status.HTTP_200_OK
    messages = detail_res.json()["messages"]
    assert len(messages) == 4  # (User 1, Asst 1, User 2, Asst 2)
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What subjects do I have?"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "Which one is lowest?"
    assert messages[3]["role"] == "assistant"

    # Delete session
    del_res = client.delete(f"/chat/sessions/{session_id}", headers=auth_headers_a)
    assert del_res.status_code == status.HTTP_200_OK

    # Verify deleted
    verify_res = client.get(f"/chat/sessions/{session_id}", headers=auth_headers_a)
    assert verify_res.status_code == status.HTTP_404_NOT_FOUND

