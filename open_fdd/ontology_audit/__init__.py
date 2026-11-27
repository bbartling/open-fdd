"""Ontology coverage audit and RDF model doctor (``open-fdd-ontology-audit``), offline-first, no NF needed.

* ``audit_requirements``: an editable CSV / XLSX of modeling requirements checked against pinned Brick, ASHRAE 223P and
  Project Haystack snapshots (or any local ontology files). Each requirement gets an evidence-backed status;
  ``VERIFIED_TERM`` only means the URI is declared in that snapshot, never that its meaning was endorsed.
* ``doctor``: classifies every class / predicate / tag a building graph uses as standard, Open-FDD or site-specific,
  flags undefined ones and checks point identity and history links. Read-only.
* ``validate_shacl``: Shifty by default (``--engine shifty``), with the vendored 223P closure when
  ``--closure`` is set. pySHACL is the optional cross-check (``advanced=True``, ``inference="none"``).
* ``nf_adapter``: optional Turtle snapshot from an NF box (``open-fdd[nf]``); nothing here imports it otherwise.

Nothing here assigns or changes fault rules, sensor bindings or NF tags.
"""
from open_fdd.ontology_audit.audit import STATUSES, AuditRow, audit_requirements
from open_fdd.ontology_audit.doctor import COMPETENCY_QUERIES, DoctorReport, doctor, run_query
from open_fdd.ontology_audit.requirements import Requirement, read_requirements
from open_fdd.ontology_audit.sources import SOURCES, LoadedSource, load_sources, refresh
from open_fdd.ontology_audit.terms import TermIndex, canonical_iri

__all__ = [
    "STATUSES", "AuditRow", "audit_requirements", "COMPETENCY_QUERIES", "DoctorReport", "doctor", "run_query",
    "Requirement", "read_requirements", "SOURCES", "LoadedSource", "load_sources", "refresh", "TermIndex",
    "canonical_iri",
]
