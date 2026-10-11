"""Ordre configurable dels tipus de permís."""

import pytest

from timeclock import database


def test_order_is_saved_and_shared_with_terminal(client):
    first = database.create_leave_type("Zeta")
    second = database.create_leave_type("Alfa")
    third = database.create_leave_type("Beta", active=False)
    assert [item["id"] for item in database.list_leave_types()] == [first, second, third]
    database.reorder_leave_types([second, third, first])
    assert [item["id"] for item in database.list_leave_types()] == [second, third, first]
    assert [item["id"] for item in database.list_active_leave_types()] == [second, first]
    database.init_database()
    assert [item["id"] for item in database.list_leave_types()] == [second, third, first]
    fourth = database.create_leave_type("Nou")
    assert [item["id"] for item in database.list_leave_types()] == [second, third, first, fourth]


@pytest.mark.parametrize("ids", [[1, 1], [1], [1, 2, 999], ["1", 2], None, "1,2", [True, 2]])
def test_invalid_orders_do_not_modify_database(client, ids):
    first = database.create_leave_type("Primer")
    second = database.create_leave_type("Segon")
    with pytest.raises(ValueError):
        database.reorder_leave_types(ids)
    assert [item["id"] for item in database.list_leave_types()] == [first, second]


def test_reorder_endpoint_requires_login_and_csrf(client):
    first = database.create_leave_type("Primer")
    second = database.create_leave_type("Segon")
    response = client.put("/api/admin/leave-types/order", json={"ids": [second, first]})
    assert response.status_code in (401, 403)
    assert [item["id"] for item in database.list_leave_types()] == [first, second]


def test_reorder_endpoint_persists(admin_client):
    first = database.create_leave_type("Primer")
    second = database.create_leave_type("Segon")
    response = admin_client.put("/api/admin/leave-types/order", json={"ids": [second, first]})
    assert response.status_code == 200
    assert [item["id"] for item in database.list_leave_types()] == [second, first]
    response = admin_client.put("/api/admin/leave-types/order", json={"ids": [first]})
    assert response.status_code == 400
    assert [item["id"] for item in database.list_leave_types()] == [second, first]


def test_existing_database_migrates_old_leave_types(client):
    first = database.create_leave_type("Zeta")
    second = database.create_leave_type("Alfa")
    with database.get_connection() as db:
        db.execute("UPDATE leave_type SET sort_order = 0")
    database.init_database()
    assert [item["id"] for item in database.list_leave_types()] == [first, second]
