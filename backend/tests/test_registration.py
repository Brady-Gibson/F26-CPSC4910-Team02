def register(client, **overrides):
    data = {
        "username": "brandnewdriver",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "first_name": "Brand",
        "last_name": "New",
        "email": "brandnewdriver@example.com",
        "phone": "8645551234",
    }

    data.update(overrides)

    return client.post("/api/register/driver", json=data)


def test_driver_registration_success(client, db):
    response = register(client)

    assert response.status_code == 201

    user_id = response.get_json()["user_id"]

    with db.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT * FROM USER_ACCOUNT WHERE user_id = %s",
            (user_id,),
        )
        user = cur.fetchone()

        cur.execute(
            "SELECT * FROM DRIVER WHERE driver_id = %s",
            (user_id,),
        )
        driver = cur.fetchone()

    assert user["username"] == "brandnewdriver"
    assert driver["participation_status"] == "APPLICANT"
    assert driver["sponsor_id"] is None


def test_registration_passwords_must_match(client):
    response = register(
        client,
        confirm_password="DifferentPassword123!",
    )

    assert response.status_code == 400


def test_registration_rejects_duplicate_username(client):
    assert register(client).status_code == 201

    response = register(
        client,
        email="another@example.com",
    )

    assert response.status_code == 400


def test_registration_rejects_bad_password(client):
    response = register(
        client,
        password="weak",
        confirm_password="weak",
    )

    assert response.status_code == 400