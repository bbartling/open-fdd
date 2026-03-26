# Engineering SPARQL examples

Use these in `Data Model Testing` after importing engineering metadata.

## AHUs and design CFM

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?ahu ?ahu_label ?design_cfm WHERE {
  ?ahu a brick:Air_Handling_Unit .
  OPTIONAL { ?ahu rdfs:label ?ahu_label . }
  OPTIONAL { ?ahu ofdd:designCFM ?design_cfm . }
}
ORDER BY ?ahu_label
```

## Equipment served by electrical panel

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?equipment ?equipment_label ?panel ?breaker WHERE {
  ?equipment ofdd:feederPanel ?panel .
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  OPTIONAL { ?equipment ofdd:feederBreaker ?breaker . }
}
ORDER BY ?panel ?equipment_label
```

## s223 connection points and conduits

```sparql
PREFIX s223: <http://data.ashrae.org/standard223#>
SELECT ?equipment ?cp ?cnx WHERE {
  ?equipment s223:hasConnectionPoint ?cp .
  OPTIONAL { ?equipment s223:cnx ?cnx . }
}
ORDER BY ?equipment ?cp
```
