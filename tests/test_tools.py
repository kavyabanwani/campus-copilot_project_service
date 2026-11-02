import ai_tools


def test_get_attendance_summary(db, student_a):
    res = ai_tools.get_attendance_summary(db, student_a)
    assert res.activity == "Checked attendance records"
    assert "overall_percentage" in res.result
    assert res.card_type in ("attendance", "attendance_summary")
    assert isinstance(res.sources, list)


def test_get_class_sessions(db, student_a):
    res = ai_tools.get_class_sessions(db, student_a)
    assert res.activity == "Checked class sessions"
    assert "sessions" in res.result


def test_simulate_attendance_change(db, student_a):
    res = ai_tools.simulate_attendance_change(db, student_a, subject="CS401", classes_to_miss=2)
    assert res.activity == "Calculated attendance impact"
    assert res.card_type == "attendance"
    assert "projected_percentage" in res.result


def test_get_timetable(db, student_a):
    res = ai_tools.get_timetable(db, student_a, day="Monday")
    assert res.activity == "Checked the timetable"
    assert res.card_type == "schedule"
    assert "classes" in res.result


def test_get_assignments(db, student_a):
    res = ai_tools.get_assignments(db, student_a)
    assert res.activity == "Checked the assignment tracker"
    assert res.card_type == "assignments"


def test_get_exams(db, student_a):
    res = ai_tools.get_exams(db, student_a)
    assert res.activity == "Checked the exam schedule"
    assert res.card_type == "exams"


def test_get_fees(db, student_a):
    res = ai_tools.get_fees(db, student_a)
    assert res.activity == "Checked the fee ledger"
    assert res.card_type == "fees"
    assert "total" in res.result
    assert "paid" in res.result


def test_get_campus_info(db, student_a):
    res = ai_tools.get_campus_info(db, student_a, topic="library")
    assert res.activity == "Looked up campus information"
    assert res.card_type == "info"
    assert "Library" in res.card_data["content"] or "library" in res.result["details"].lower()


def test_get_campus_events(db, student_a):
    res = ai_tools.get_campus_events(db, student_a, days_ahead=30)
    assert res.activity == "Checked campus events schedule"
    assert res.card_type == "events"
    assert len(res.result["events"]) > 0
    assert any(e["is_demo"] for e in res.result["events"])


def test_search_campus_documents(db, student_a):
    res = ai_tools.search_campus_documents(db, student_a, query="condonation attendance shortage")
    assert res.activity == "Searched campus documents"
    assert res.card_type == "policy"
    assert "passages" in res.result
    assert "[UNTRUSTED CAMPUS DOCUMENT:" in res.result["passages"][0]["text"]

