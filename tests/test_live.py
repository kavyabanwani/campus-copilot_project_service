import os
import pytest
import ai_agent
from config import settings


@pytest.mark.live
def test_live_groq_tool_calling(db, student_a):
    key = os.environ.get("GROQ_API_KEY") or getattr(settings, "GROQ_API_KEY", "")
    if not key or "replace" in key or key.strip() == "":
        pytest.skip("GROQ_API_KEY not provided for live test")

    question = "How much attendance do I have in DBMS?"
    answer = ai_agent.run_agent(question, student_a, db)

    assert answer.content
    # Assert a tool call occurred
    assert any("attendance" in step.lower() for step in answer.activity_steps)

