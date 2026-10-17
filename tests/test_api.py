H = {"x-device-id": "test-device"}

NETFLIX = "Rs.649.00 debited from a/c XX1234 to NETFLIX on 01-05-24. UPI Ref 123"


def test_brokerages(client):
    r = client.get("/brokerages")
    assert r.status_code == 200


def test_merchants_catalogue(client):
    r = client.get("/merchants")
    assert r.status_code == 200
    assert client.get("/merchants/netflix").status_code == 200


def test_parse_sms_detects_amount_and_currency(client):
    r = client.post("/parse-sms", json={"text": NETFLIX}, headers=H)
    assert r.status_code == 200
    txs = r.json()["parsed_transactions"]
    assert len(txs) == 1
    assert txs[0]["amount"] == 649.0


def test_parse_sms_ignores_one_time_card_spend(client):
    r = client.post("/parse-sms", json={"text": "Rs 500 spent on card XX12. Avl limit Rs 20000"}, headers=H)
    assert r.json()["parsed_transactions"] == []


def test_parse_sms_skips_lines_without_amount(client):
    r = client.post("/parse-sms", json={"text": "hello\nno money here"}, headers=H)
    assert r.json()["parsed_transactions"] == []


def test_subscriptions_are_scoped_per_device(client):
    client.post("/parse-sms", json={"text": NETFLIX}, headers=H)
    mine = client.get("/subscriptions", headers=H).json()
    other = client.get("/subscriptions", headers={"x-device-id": "someone-else"}).json()
    assert mine != other


def test_market_scan_requires_api_key(client):
    r = client.get("/market-scan")
    assert r.status_code == 503
