"""Validate the app's Turtle: two parsers + Haystack-style orphan checks + time-series refs.
usage: python check_ttl.py <file.ttl>   (exit 1 on any problem)"""
import sys
from rdflib import Graph, RDF, RDFS, URIRef, BNode, Namespace
import pyoxigraph as ox

REFNS = Namespace("https://brickschema.org/schema/Brick/ref#")
path = sys.argv[1]
problems = []
with open(path, "rb") as f:
    ox_triples = list(ox.parse(f, format=ox.RdfFormat.TURTLE))
print(f"oxigraph: parsed OK, {len(ox_triples)} triples")
g = Graph()
g.parse(path, format="turtle")
g2 = Graph()
g2.parse(data=g.serialize(format="nt"), format="nt")
print(f"rdflib:   parsed OK, {len(g)} triples; N-Triples round trip {'OK' if len(g2) == len(g) else 'MISMATCH'}")
if len(g2) != len(g) or len(g) != len(ox_triples):
    problems.append("triple counts differ between parsers / round trip")

local = [ns for p, ns in g.namespaces() if p == "local"][0]
is_local = lambda n: isinstance(n, URIRef) and str(n).startswith(str(local))
REF = {p for p in g.predicates() if str(p).endswith("Ref")}
HAS_TAG = [p for p in g.predicates() if str(p).endswith("hasTag")][0]
typed = {s for s in g.subjects(RDF.type, None) if not isinstance(s, BNode)}

for s, p, o in g.triples((None, None, None)):
    if p in REF and o not in typed:
        problems.append(f"dangling ref: {s} {p} {o}")
used_local = {o for _, _, o in g if is_local(o)} | {s for s in g.subjects() if is_local(s)}
for n in sorted(used_local - typed):
    problems.append(f"undefined local term (orphan): {n}")
for s in typed:
    if (s, RDFS.label, None) not in g:
        problems.append(f"no label: {s}")
linked = {o for s, p, o in g if p in REF} | {s for s, p, o in g if p in REF}
points = []
for s in typed:
    kinds = {str(t).rsplit("/", 1)[-1] for t in g.objects(s, RDF.type)}
    if "point" in kinds:
        points.append(s)
    if kinds & {"point", "equip", "device"} and not any(g.objects(s, p) for p in REF if str(p).endswith("siteRef")):
        problems.append(f"no siteRef: {s}")
    if kinds & {"site", "equip", "device", "point", "weatherStation"} and s not in linked:
        problems.append(f"disconnected entity: {s}")

# Slice 6: every point has exactly one NF time-series reference with a uuid, stored at a defined store.
nf_store = URIRef(str(local) + "store_nf")
for pt in points:
    refs = list(g.objects(pt, REFNS.hasExternalReference))
    if not refs:
        problems.append(f"point without time-series reference: {pt}")
        continue
    for r in refs:
        if (r, RDF.type, REFNS.TimeseriesReference) not in g:
            problems.append(f"reference is not a ref:TimeseriesReference: {pt}")
        for st in g.objects(r, REFNS.storedAt):
            if st not in typed:
                problems.append(f"storedAt undefined store {st}: {pt}")
    nf = [r for r in refs if (r, REFNS.storedAt, nf_store) in g]
    if len(nf) != 1:
        problems.append(f"expected exactly 1 NF time-series reference, got {len(nf)}: {pt}")
        continue
    ids = [str(i) for i in g.objects(nf[0], REFNS.hasTimeseriesId)]
    if len(ids) != 1 or not ids[0].strip():
        problems.append(f"NF reference needs exactly one non-empty hasTimeseriesId: {pt}")
if not points:
    problems.append("no points in graph")

print(f"entities: {len(typed)}  points: {len(points)}  refs: {sum(1 for _, p, _ in g if p in REF)}  "
      f"tags: {sum(1 for _ in g.triples((None, HAS_TAG, None)))}  "
      f"timeseries refs: {sum(1 for _ in g.triples((None, REFNS.hasExternalReference, None)))}")
print("PROBLEMS:" if problems else "no problems: valid Turtle, no dangling refs, no orphans, every point has a time-series ref")
for x in problems:
    print("  -", x)
sys.exit(1 if problems else 0)
