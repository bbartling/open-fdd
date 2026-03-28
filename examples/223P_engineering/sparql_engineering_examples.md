# Engineering SPARQL examples

Use these in **Data Model Testing** after importing engineering metadata (or compare against `engineering_graph_mini.ttl` in an offline RDF tool).

## AHU → VAV topology (Brick feeds)

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?upstream ?upstream_label ?downstream ?downstream_label WHERE {
  ?upstream brick:feeds ?downstream .
  OPTIONAL { ?upstream rdfs:label ?upstream_label . }
  OPTIONAL { ?downstream rdfs:label ?downstream_label . }
}
ORDER BY ?upstream_label ?downstream_label
```

## AHUs with design CFM **and** cooling tons (optimization / penalty context)

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?ahu ?ahu_label ?design_cfm ?tons WHERE {
  ?ahu a brick:Air_Handling_Unit .
  OPTIONAL { ?ahu rdfs:label ?ahu_label . }
  OPTIONAL { ?ahu ofdd:designCFM ?design_cfm . }
  OPTIONAL { ?ahu ofdd:coolingCapacityTons ?tons . }
}
ORDER BY ?ahu_label
```

## Points on an AHU that have BACnet + timeseries refs (Brick `ref:`)

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
SELECT ?point ?label ?rule_in ?oid WHERE {
  ?ahu a brick:Air_Handling_Unit .
  ?point brick:isPointOf ?ahu .
  OPTIONAL { ?point rdfs:label ?label . }
  OPTIONAL { ?point ofdd:mapsToRuleInput ?rule_in . }
  ?point ref:hasExternalReference ?rep .
  ?rep a ref:BACnetReference .
  OPTIONAL { ?rep bacnet:object-identifier ?oid . }
}
ORDER BY ?label
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

## BACnet devices present in the graph (discovery / gateway optimization)

```sparql
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?dev ?label ?inst WHERE {
  ?dev a bacnet:Device .
  OPTIONAL { ?dev rdfs:label ?label . }
  OPTIONAL { ?dev bacnet:device-instance ?inst . }
}
ORDER BY ?inst
```
