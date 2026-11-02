import ai_agent
from llm_client import ModelReply, ToolCall


def test_agent_loop_tool_call_to_final_answer(monkeypatch, db, student_a):
    rounds = [
        # Round 1: model calls tool
        ModelReply(
            text="",
            tool_calls=[ToolCall(name="get_attendance_summary", arguments={}, call_id="c1")],
        ),
        # Round 2: model provides grounded answer
        ModelReply(
            text="Your overall attendance is above the 75% minimum requirement.",
            tool_calls=[],
        ),
    ]

    def mock_chat(system_instruction, messages, tools):
        return rounds.pop(0)

    monkeypatch.setattr("llm_client.chat", mock_chat)

    answer = ai_agent.run_agent("How is my attendance?", student_a, db)

    assert "75% minimum" in answer.content
    assert answer.card_type in ("attendance", "attendance_summary")
    assert answer.card_data is not None
    assert "Checked attendance records" in answer.activity_steps
    assert "Writing your answer" in answer.activity_steps
    assert len(answer.cards) >= 1


def test_agent_loop_multiple_cards(monkeypatch, db, student_a):
    rounds = [
        # Round 1: model calls both timetable and attendance
        ModelReply(
            text="",
            tool_calls=[
                ToolCall(name="get_timetable", arguments={"day": "Monday"}, call_id="c1"),
                ToolCall(name="get_attendance_summary", arguments={}, call_id="c2"),
            ],
        ),
        # Round 2: final answer
        ModelReply(
            text="On Monday you have scheduled classes, and your attendance is safe.",
            tool_calls=[],
        ),
    ]

    def mock_chat(system_instruction, messages, tools):
        return rounds.pop(0)

    monkeypatch.setattr("llm_client.chat", mock_chat)

    answer = ai_agent.run_agent("Can I skip classes on Monday?", student_a, db)

    assert "Monday you have scheduled classes" in answer.content
    # Multiple cards should be collected in answer.cards
    assert len(answer.cards) >= 2
    card_types = [c["type"] for c in answer.cards]
    assert "schedule" in card_types
    assert any("attendance" in t for t in card_types)
