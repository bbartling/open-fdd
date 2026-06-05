from __future__ import annotations


def test_sparql_predefined_catalog(client):
    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    r = client.get("/api/model/sparql/predefined")
    assert r.status_code == 200
    body = r.json()
    assert "default_query" in body
    assert "queries" in body
    assert len(body["queries"]) >= 5
    assert any(q["id"] == "sites" for q in body["queries"])


def test_sparql_run_select(client):
    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    client.post("/api/model/sync-ttl")
    query = """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT (COUNT(?s) AS ?count) WHERE { ?s a brick:Site . }"""
    r = client.post("/api/model/sparql", json={"query": query})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "bindings" in body
    assert body["bindings"]
    assert "count" in body["bindings"][0]


def test_sparql_rejects_update(client):
    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    r = client.post(
        "/api/model/sparql",
        json={"query": "DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }"},
    )
    assert r.status_code == 400
    assert "read-only" in r.json()["detail"].lower()


def test_sparql_requires_auth(raw_client):
    r = raw_client.post("/api/model/sparql", json={"query": "SELECT ?x WHERE { ?x ?y ?z } LIMIT 1"})
    assert r.status_code == 401
