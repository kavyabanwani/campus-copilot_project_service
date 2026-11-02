from fastapi import status


def test_auth_registration_and_login(client):
    # Valid registration
    payload = {
        "roll_number": "CS22B099",
        "full_name": "Charlie Student",
        "email": "charlie@campus.edu",
        "department": "Computer Science",
        "semester": 4,
        "password": "StrongPassword123",
    }
    res = client.post("/auth/register", json=payload)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert "access_token" in data
    assert data["student"]["email"] == "charlie@campus.edu"
    assert data["student"]["role"] == "student"

    # Login
    login_res = client.post(
        "/auth/login",
        json={"email": "charlie@campus.edu", "password": "StrongPassword123"},
    )
    assert login_res.status_code == status.HTTP_200_OK
    assert "access_token" in login_res.json()

    # Login with roll number
    roll_login = client.post(
        "/auth/login",
        json={"email": "CS22B099", "password": "StrongPassword123"},
    )
    assert roll_login.status_code == status.HTTP_200_OK


def test_password_length_validation(client):
    # Too short (<8 chars)
    short_payload = {
        "roll_number": "CS22B100",
        "full_name": "Short Pass",
        "email": "short@campus.edu",
        "department": "Computer Science",
        "semester": 4,
        "password": "12345",
    }
    res = client.post("/auth/register", json=short_payload)
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "8 characters" in res.text

    # Too long (>72 bytes)
    long_payload = {
        "roll_number": "CS22B101",
        "full_name": "Long Pass",
        "email": "long@campus.edu",
        "department": "Computer Science",
        "semester": 4,
        "password": "A" * 75,
    }
    res2 = client.post("/auth/register", json=long_payload)
    assert res2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "72 bytes" in res2.text


def test_department_and_semester_validation(client):
    # Invalid department
    bad_dept = {
        "roll_number": "CS22B102",
        "full_name": "Bad Dept",
        "email": "baddept@campus.edu",
        "department": "Aeronautical Engineering",
        "semester": 4,
        "password": "Password123",
    }
    res = client.post("/auth/register", json=bad_dept)
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Invalid semester
    bad_sem = {
        "roll_number": "CS22B103",
        "full_name": "Bad Sem",
        "email": "badsem@campus.edu",
        "department": "Computer Science",
        "semester": 10,
        "password": "Password123",
    }
    res2 = client.post("/auth/register", json=bad_sem)
    assert res2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_change_password(client, auth_headers_a):
    res = client.post(
        "/auth/change-password",
        json={"current_password": "Password123", "new_password": "NewStrongPass123"},
        headers=auth_headers_a,
    )
    assert res.status_code == status.HTTP_200_OK

    # Verify new password works
    login_res = client.post(
        "/auth/login",
        json={"email": "alice@campus.edu", "password": "NewStrongPass123"},
    )
    assert login_res.status_code == status.HTTP_200_OK


def test_auth_me(client, auth_headers_a, student_a):
    res = client.get("/auth/me", headers=auth_headers_a)
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["student_id"] == student_a.student_id

