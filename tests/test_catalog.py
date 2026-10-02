def test_only_admin_can_manage_catalog(client, user, admin):
    assert client.post("/tests", json={"name": "CBC"}, headers=user).status_code == 403
    assert client.post("/centres", json={"name": "C", "location": "Delhi"}).status_code == 401
    assert client.post("/tests", json={"name": "CBC"}, headers=admin).status_code == 201


def test_centre_detail_lists_tests_and_prices(client, catalog):
    r = client.get(f"/centres/{catalog['centre_id']}")
    assert r.status_code == 200
    assert r.json()["tests"] == [{"test_id": catalog["test_id"], "test_name": "CBC", "price": 499.5}]


def test_filters_and_pagination(client, admin, catalog):
    client.post("/centres", json={"name": "Second", "location": "Delhi"}, headers=admin)
    assert len(client.get("/centres").json()) == 2
    assert len(client.get("/centres", params={"limit": 1}).json()) == 1
    assert [c["name"] for c in client.get("/centres", params={"location": "delhi"}).json()] == ["Second"]
    assert [c["name"] for c in client.get("/centres", params={"test_id": catalog["test_id"]}).json()] == ["EVE Central"]
    assert client.get("/centres", params={"limit": 0}).status_code == 422


def test_catalog_edge_cases(client, admin, catalog):
    assert client.get("/centres/9999").status_code == 404
    dup = client.post(f"/centres/{catalog['centre_id']}/tests", json={"test_id": catalog["test_id"], "price": "10"}, headers=admin)
    assert dup.status_code == 409
    bad_price = client.post(f"/centres/{catalog['centre_id']}/tests", json={"test_id": catalog["test_id"], "price": "-5"}, headers=admin)
    assert bad_price.status_code == 422
    assert client.post("/tests", json={"name": "CBC"}, headers=admin).status_code == 409
