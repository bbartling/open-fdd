---
title: Grafana SQL cookbook
parent: How-to Guides
nav_order: 40
---


# Grafana SQL cookbook — 


## BACnet 

* Dashboard Variables (Required for Dropdowns)

Before creating the panels below, you must set up the dashboard variables so the drop-down menus work. 

In Grafana, go to **Dashboard Settings (gear icon) > Variables > Add variable**. Set the **Type** to `Query`, select your TimescaleDB datasource, and use the following queries:

### 1. Site Variable
* **Name:** `site`
* **Query:**

```sql
SELECT s.name AS __text, s.id::text AS __value 
FROM sites s 
ORDER BY s.name;
```

### 2. Device Variable

* **Name:** `device`
* **Query:**

```sql
SELECT DISTINCT p.bacnet_device_id::text AS __text, p.bacnet_device_id::text AS __value 
FROM points p 
WHERE p.site_id::text = '$site' 
  AND p.bacnet_device_id IS NOT NULL 
ORDER BY 1;
```

### 3. Point Variable

* **Name:** `point`
* **Query:**

```sql
SELECT p.external_id AS __text, p.external_id AS __value 
FROM points p 
WHERE p.site_id::text = '$site' 
  AND p.bacnet_device_id::text = '$device' 
ORDER BY 1;
```

---

### BACnet only data

Insert Snip here

* This dashboard uses `point`, `device`, and `site` variables.

```json
{
  "id": 1,
  "type": "timeseries",
  "title": "BACnet",
  "gridPos": {
    "x": 0,
    "y": 0,
    "h": 16,
    "w": 24
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "drawStyle": "line",
        "lineInterpolation": "linear",
        "barAlignment": 0,
        "barWidthFactor": 0.6,
        "lineWidth": 1,
        "fillOpacity": 0,
        "gradientMode": "none",
        "spanNulls": false,
        "insertNulls": false,
        "showPoints": "auto",
        "showValues": false,
        "pointSize": 5,
        "stacking": {
          "mode": "none",
          "group": "A"
        },
        "axisPlacement": "auto",
        "axisLabel": "",
        "axisColorMode": "text",
        "axisBorderShow": false,
        "scaleDistribution": {
          "type": "linear"
        },
        "axisCenteredZero": false,
        "hideFrom": {
          "tooltip": false,
          "viz": false,
          "legend": false
        },
        "thresholdsStyle": {
          "mode": "off"
        }
      },
      "color": {
        "mode": "palette-classic"
      },
      "mappings": [],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "color": "green",
            "value": null
          },
          {
            "color": "red",
            "value": 80
          }
        ]
      }
    },
    "overrides": []
  },
  "pluginVersion": "12.4.0",
  "targets": [
    {
      "editorMode": "code",
      "format": "time_series",
      "rawQuery": true,
      "rawSql": "SELECT\n  time_bucket(\n    make_interval(secs => ($__interval_ms / 1000)::int),\n    tr.ts\n  ) AS \"time\",\n  avg(tr.value) AS \"value\",\n  p.external_id AS \"metric\"\nFROM timeseries_readings tr\nJOIN points p ON p.id = tr.point_id\nWHERE $__timeFilter(tr.ts)\n  AND p.site_id::text IN (${site:sqlstring})\n  AND p.bacnet_device_id::text IN (${device:sqlstring})\n  AND p.external_id IN (${point:sqlstring})\nGROUP BY 1, 3\nORDER BY 1, 3;",
      "refId": "A",
      "sql": {
        "columns": [
          {
            "parameters": [],
            "type": "function"
          }
        ],
        "groupBy": [
          {
            "property": {
              "type": "string"
            },
            "type": "groupBy"
          }
        ],
        "limit": 50
      }
    }
  ],
  "datasource": {
    "uid": "openfdd_timescale"
  },
  "options": {
    "tooltip": {
      "mode": "single",
      "sort": "none",
      "hideZeros": false
    },
    "legend": {
      "showLegend": true,
      "displayMode": "list",
      "placement": "bottom",
      "calcs": []
    }
  }
}
```

## BACnet Plus Fault Data


```json
{
  "id": null,
  "type": "timeseries",
  "title": "BACnet Telemetry w/ Fault Overlays",
  "gridPos": {
    "x": 0,
    "y": 16,
    "h": 12,
    "w": 24
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "drawStyle": "line",
        "lineInterpolation": "linear",
        "barAlignment": 0,
        "barWidthFactor": 0.6,
        "lineWidth": 2,
        "fillOpacity": 10,
        "gradientMode": "none",
        "spanNulls": false,
        "insertNulls": false,
        "showPoints": "never",
        "showValues": false,
        "pointSize": 5,
        "stacking": {
          "mode": "none",
          "group": "A"
        },
        "axisPlacement": "left",
        "axisLabel": "",
        "axisColorMode": "text",
        "axisBorderShow": false,
        "scaleDistribution": {
          "type": "linear"
        },
        "axisCenteredZero": false,
        "hideFrom": {
          "tooltip": false,
          "viz": false,
          "legend": false
        },
        "thresholdsStyle": {
          "mode": "off"
        }
      },
      "color": {
        "mode": "palette-classic"
      },
      "mappings": [],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "value": null,
            "color": "green"
          },
          {
            "value": 80,
            "color": "red"
          }
        ]
      }
    },
    "overrides": [
      {
        "matcher": {
          "id": "byFrameRefID",
          "options": "B"
        },
        "properties": [
          {
            "id": "custom.axisPlacement",
            "value": "right"
          },
          {
            "id": "custom.drawStyle",
            "value": "bars"
          },
          {
            "id": "custom.fillOpacity",
            "value": 30
          },
          {
            "id": "min",
            "value": 0
          },
          {
            "id": "max",
            "value": 1.2
          },
          {
            "id": "custom.axisLabel",
            "value": "Fault Active (1 = Yes)"
          }
        ]
      }
    ]
  },
  "pluginVersion": "12.4.0",
  "targets": [
    {
      "refId": "A",
      "format": "time_series",
      "rawQuery": true,
      "editorMode": "code",
      "rawSql": "SELECT\n  time_bucket(make_interval(secs => ($__interval_ms / 1000)::int), tr.ts) AS \"time\",\n  avg(tr.value) AS \"value\",\n  p.external_id AS \"metric\"\nFROM timeseries_readings tr\nJOIN points p ON p.id = tr.point_id\nWHERE $__timeFilter(tr.ts)\n  AND p.site_id::text IN (${site:sqlstring})\n  AND p.bacnet_device_id::text IN (${device:sqlstring})\n  AND p.external_id IN (${point:sqlstring})\nGROUP BY 1, 3\nORDER BY 1, 3;"
    },
    {
      "refId": "B",
      "format": "time_series",
      "rawQuery": true,
      "editorMode": "code",
      "rawSql": "SELECT\n  time_bucket(make_interval(secs => ($__interval_ms / 1000)::int), fr.ts) AS \"time\",\n  max(fr.flag_value) AS \"value\",\n  fd.name AS \"metric\"\nFROM fault_results fr\nJOIN fault_definitions fd ON fd.fault_id = fr.fault_id\nWHERE $__timeFilter(fr.ts)\n  AND (fr.site_id IN (${site:sqlstring}) OR fr.site_id IN (SELECT name FROM sites WHERE id::text IN (${site:sqlstring})))\nGROUP BY 1, 3\nORDER BY 1, 3;"
    }
  ],
  "datasource": {
    "uid": "openfdd_timescale"
  },
  "options": {
    "tooltip": {
      "mode": "multi",
      "sort": "none",
      "hideZeros": false
    },
    "legend": {
      "showLegend": true,
      "displayMode": "list",
      "placement": "bottom",
      "calcs": []
    }
  }
}

```

## Weather


### Temp RH Dewpoint

```json
{
  "id": 21,
  "type": "timeseries",
  "title": "Weather — Temp / RH / Dewpoint",
  "gridPos": {
    "x": 0,
    "y": 0,
    "h": 10,
    "w": 24
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "drawStyle": "line",
        "lineInterpolation": "linear",
        "barAlignment": 0,
        "barWidthFactor": 0.6,
        "lineWidth": 2,
        "fillOpacity": 12,
        "gradientMode": "none",
        "spanNulls": false,
        "insertNulls": false,
        "showPoints": "never",
        "showValues": false,
        "pointSize": 4,
        "stacking": {
          "mode": "none",
          "group": "A"
        },
        "axisPlacement": "left",
        "axisLabel": "°F",
        "axisColorMode": "text",
        "axisBorderShow": false,
        "scaleDistribution": {
          "type": "linear"
        },
        "axisCenteredZero": false,
        "hideFrom": {
          "tooltip": false,
          "viz": false,
          "legend": false
        },
        "thresholdsStyle": {
          "mode": "off"
        }
      },
      "color": {
        "mode": "palette-classic"
      },
      "mappings": [],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "color": "green",
            "value": null
          },
          {
            "color": "red",
            "value": 80
          }
        ]
      }
    },
    "overrides": [
      {
        "matcher": {
          "id": "byName",
          "options": "temp_f"
        },
        "properties": [
          {
            "id": "unit",
            "value": "fahrenheit"
          },
          {
            "id": "custom.axisPlacement",
            "value": "left"
          },
          {
            "id": "custom.axisLabel",
            "value": "°F"
          }
        ]
      },
      {
        "matcher": {
          "id": "byName",
          "options": "dewpoint_f"
        },
        "properties": [
          {
            "id": "unit",
            "value": "fahrenheit"
          },
          {
            "id": "custom.axisPlacement",
            "value": "left"
          }
        ]
      },
      {
        "matcher": {
          "id": "byName",
          "options": "rh_pct"
        },
        "properties": [
          {
            "id": "unit",
            "value": "percent"
          },
          {
            "id": "custom.axisPlacement",
            "value": "right"
          },
          {
            "id": "custom.axisLabel",
            "value": "RH (%)"
          },
          {
            "id": "min",
            "value": 0
          },
          {
            "id": "max",
            "value": 100
          }
        ]
      }
    ]
  },
  "pluginVersion": "12.4.0",
  "targets": [
    {
      "refId": "A",
      "editorMode": "code",
      "rawQuery": true,
      "format": "time_series",
      "rawSql": "SELECT\n  time_bucket(make_interval(secs => ($__interval_ms / 1000)::int), tr.ts) AS \"time\",\n  avg(tr.value) AS \"value\",\n  p.external_id AS \"metric\"\nFROM timeseries_readings tr\nJOIN points p ON p.id = tr.point_id\nWHERE $__timeFilter(tr.ts)\n  AND p.site_id::text IN (${site:sqlstring})\n  AND p.external_id IN ('temp_f','rh_pct','dewpoint_f')\nGROUP BY 1, 3\nORDER BY 1, 3;"
    }
  ],
  "datasource": {
    "uid": "openfdd_timescale"
  },
  "options": {
    "tooltip": {
      "mode": "single",
      "sort": "none",
      "hideZeros": false
    },
    "legend": {
      "showLegend": true,
      "displayMode": "list",
      "placement": "bottom",
      "calcs": []
    }
  }
}
```





### Wind Speed Gusts Direction


```json

{
  "id": 22,
  "type": "timeseries",
  "title": "Weather — Wind (Speed / Gust / Direction)",
  "gridPos": {
    "x": 0,
    "y": 10,
    "h": 9,
    "w": 24
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "drawStyle": "line",
        "lineInterpolation": "linear",
        "barAlignment": 0,
        "barWidthFactor": 0.6,
        "lineWidth": 2,
        "fillOpacity": 10,
        "gradientMode": "none",
        "spanNulls": false,
        "insertNulls": false,
        "showPoints": "never",
        "showValues": false,
        "pointSize": 4,
        "stacking": {
          "mode": "none",
          "group": "A"
        },
        "axisPlacement": "left",
        "axisLabel": "mph",
        "axisColorMode": "text",
        "axisBorderShow": false,
        "scaleDistribution": {
          "type": "linear"
        },
        "axisCenteredZero": false,
        "hideFrom": {
          "tooltip": false,
          "viz": false,
          "legend": false
        },
        "thresholdsStyle": {
          "mode": "off"
        }
      },
      "color": {
        "mode": "palette-classic"
      },
      "mappings": [],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "color": "green",
            "value": null
          },
          {
            "color": "red",
            "value": 80
          }
        ]
      }
    },
    "overrides": [
      {
        "matcher": {
          "id": "byName",
          "options": "wind_mph"
        },
        "properties": [
          {
            "id": "unit",
            "value": "mph"
          },
          {
            "id": "custom.axisPlacement",
            "value": "left"
          },
          {
            "id": "custom.axisLabel",
            "value": "mph"
          },
          {
            "id": "min",
            "value": 0
          }
        ]
      },
      {
        "matcher": {
          "id": "byName",
          "options": "gust_mph"
        },
        "properties": [
          {
            "id": "unit",
            "value": "mph"
          },
          {
            "id": "custom.axisPlacement",
            "value": "left"
          },
          {
            "id": "min",
            "value": 0
          }
        ]
      },
      {
        "matcher": {
          "id": "byName",
          "options": "wind_dir_deg"
        },
        "properties": [
          {
            "id": "unit",
            "value": "degrees"
          },
          {
            "id": "custom.axisPlacement",
            "value": "right"
          },
          {
            "id": "custom.axisLabel",
            "value": "°"
          },
          {
            "id": "min",
            "value": 0
          },
          {
            "id": "max",
            "value": 360
          }
        ]
      }
    ]
  },
  "pluginVersion": "12.4.0",
  "targets": [
    {
      "refId": "A",
      "editorMode": "code",
      "rawQuery": true,
      "format": "time_series",
      "rawSql": "SELECT\n  time_bucket(make_interval(secs => ($__interval_ms / 1000)::int), tr.ts) AS \"time\",\n  avg(tr.value) AS \"value\",\n  p.external_id AS \"metric\"\nFROM timeseries_readings tr\nJOIN points p ON p.id = tr.point_id\nWHERE $__timeFilter(tr.ts)\n  AND p.site_id::text IN (${site:sqlstring})\n  AND p.external_id IN ('wind_mph','gust_mph','wind_dir_deg')\nGROUP BY 1, 3\nORDER BY 1, 3;"
    }
  ],
  "datasource": {
    "uid": "openfdd_timescale"
  },
  "options": {
    "tooltip": {
      "mode": "single",
      "sort": "none",
      "hideZeros": false
    },
    "legend": {
      "showLegend": true,
      "displayMode": "list",
      "placement": "bottom",
      "calcs": []
    }
  }
}
```


### Wind Speed Gust Direction


```json
{
  "id": 22,
  "type": "timeseries",
  "title": "Weather — Wind (Speed / Gust / Direction)",
  "gridPos": {
    "x": 0,
    "y": 10,
    "h": 9,
    "w": 24
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "drawStyle": "line",
        "lineInterpolation": "linear",
        "barAlignment": 0,
        "barWidthFactor": 0.6,
        "lineWidth": 2,
        "fillOpacity": 10,
        "gradientMode": "none",
        "spanNulls": false,
        "insertNulls": false,
        "showPoints": "never",
        "showValues": false,
        "pointSize": 4,
        "stacking": {
          "mode": "none",
          "group": "A"
        },
        "axisPlacement": "left",
        "axisLabel": "mph",
        "axisColorMode": "text",
        "axisBorderShow": false,
        "scaleDistribution": {
          "type": "linear"
        },
        "axisCenteredZero": false,
        "hideFrom": {
          "tooltip": false,
          "viz": false,
          "legend": false
        },
        "thresholdsStyle": {
          "mode": "off"
        }
      },
      "color": {
        "mode": "palette-classic"
      },
      "mappings": [],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "color": "green",
            "value": null
          },
          {
            "color": "red",
            "value": 80
          }
        ]
      }
    },
    "overrides": [
      {
        "matcher": {
          "id": "byName",
          "options": "wind_mph"
        },
        "properties": [
          {
            "id": "unit",
            "value": "mph"
          },
          {
            "id": "custom.axisPlacement",
            "value": "left"
          },
          {
            "id": "custom.axisLabel",
            "value": "mph"
          },
          {
            "id": "min",
            "value": 0
          }
        ]
      },
      {
        "matcher": {
          "id": "byName",
          "options": "gust_mph"
        },
        "properties": [
          {
            "id": "unit",
            "value": "mph"
          },
          {
            "id": "custom.axisPlacement",
            "value": "left"
          },
          {
            "id": "min",
            "value": 0
          }
        ]
      },
      {
        "matcher": {
          "id": "byName",
          "options": "wind_dir_deg"
        },
        "properties": [
          {
            "id": "unit",
            "value": "degrees"
          },
          {
            "id": "custom.axisPlacement",
            "value": "right"
          },
          {
            "id": "custom.axisLabel",
            "value": "°"
          },
          {
            "id": "min",
            "value": 0
          },
          {
            "id": "max",
            "value": 360
          }
        ]
      }
    ]
  },
  "pluginVersion": "12.4.0",
  "targets": [
    {
      "refId": "A",
      "editorMode": "code",
      "rawQuery": true,
      "format": "time_series",
      "rawSql": "SELECT\n  time_bucket(make_interval(secs => ($__interval_ms / 1000)::int), tr.ts) AS \"time\",\n  avg(tr.value) AS \"value\",\n  p.external_id AS \"metric\"\nFROM timeseries_readings tr\nJOIN points p ON p.id = tr.point_id\nWHERE $__timeFilter(tr.ts)\n  AND p.site_id::text IN (${site:sqlstring})\n  AND p.external_id IN ('wind_mph','gust_mph','wind_dir_deg')\nGROUP BY 1, 3\nORDER BY 1, 3;"
    }
  ],
  "datasource": {
    "uid": "openfdd_timescale"
  },
  "options": {
    "tooltip": {
      "mode": "single",
      "sort": "none",
      "hideZeros": false
    },
    "legend": {
      "showLegend": true,
      "displayMode": "list",
      "placement": "bottom",
      "calcs": []
    }
  }
}

```


### Solar Radiation 


```json
{
  "id": 23,
  "type": "timeseries",
  "title": "Weather — Solar / Radiation (W/m²)",
  "gridPos": {
    "x": 0,
    "y": 19,
    "h": 9,
    "w": 24
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "drawStyle": "line",
        "lineInterpolation": "linear",
        "barAlignment": 0,
        "barWidthFactor": 0.6,
        "lineWidth": 2,
        "fillOpacity": 10,
        "gradientMode": "none",
        "spanNulls": false,
        "insertNulls": false,
        "showPoints": "never",
        "showValues": false,
        "pointSize": 4,
        "stacking": {
          "mode": "none",
          "group": "A"
        },
        "axisPlacement": "left",
        "axisLabel": "W/m²",
        "axisColorMode": "text",
        "axisBorderShow": false,
        "scaleDistribution": {
          "type": "linear"
        },
        "axisCenteredZero": true,
        "hideFrom": {
          "tooltip": false,
          "viz": false,
          "legend": false
        },
        "thresholdsStyle": {
          "mode": "off"
        }
      },
      "color": {
        "mode": "palette-classic"
      },
      "mappings": [],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "color": "green",
            "value": null
          },
          {
            "color": "red",
            "value": 80
          }
        ]
      },
      "unit": "wattperm2",
      "min": 0
    },
    "overrides": [
      {
        "matcher": {
          "id": "byName",
          "options": "shortwave_wm2"
        },
        "properties": [
          {
            "id": "min",
            "value": 0
          }
        ]
      },
      {
        "matcher": {
          "id": "byName",
          "options": "direct_wm2"
        },
        "properties": [
          {
            "id": "min",
            "value": 0
          }
        ]
      },
      {
        "matcher": {
          "id": "byName",
          "options": "diffuse_wm2"
        },
        "properties": [
          {
            "id": "min",
            "value": 0
          }
        ]
      },
      {
        "matcher": {
          "id": "byName",
          "options": "gti_wm2"
        },
        "properties": [
          {
            "id": "min",
            "value": 0
          }
        ]
      }
    ]
  },
  "pluginVersion": "12.4.0",
  "targets": [
    {
      "refId": "A",
      "editorMode": "code",
      "rawQuery": true,
      "format": "time_series",
      "rawSql": "SELECT\n  time_bucket(make_interval(secs => ($__interval_ms / 1000)::int), tr.ts) AS \"time\",\n  avg(tr.value) AS \"value\",\n  p.external_id AS \"metric\"\nFROM timeseries_readings tr\nJOIN points p ON p.id = tr.point_id\nWHERE $__timeFilter(tr.ts)\n  AND p.site_id::text IN (${site:sqlstring})\n  AND p.external_id IN ('shortwave_wm2','direct_wm2','diffuse_wm2','gti_wm2')\nGROUP BY 1, 3\nORDER BY 1, 3;"
    }
  ],
  "datasource": {
    "uid": "openfdd_timescale"
  },
  "options": {
    "tooltip": {
      "mode": "single",
      "sort": "none",
      "hideZeros": false
    },
    "legend": {
      "showLegend": true,
      "displayMode": "list",
      "placement": "bottom",
      "calcs": []
    }
  }
}
```

### Cloud Cover


```json

{
  "id": 24,
  "type": "timeseries",
  "title": "Weather — Cloud Cover (%)",
  "gridPos": {
    "x": 0,
    "y": 28,
    "h": 7,
    "w": 24
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "drawStyle": "line",
        "lineInterpolation": "linear",
        "barAlignment": 0,
        "barWidthFactor": 0.6,
        "lineWidth": 2,
        "fillOpacity": 35,
        "gradientMode": "opacity",
        "spanNulls": false,
        "insertNulls": false,
        "showPoints": "never",
        "showValues": false,
        "pointSize": 4,
        "stacking": {
          "mode": "none",
          "group": "A"
        },
        "axisPlacement": "left",
        "axisLabel": "Cloud (%)",
        "axisColorMode": "text",
        "axisBorderShow": false,
        "scaleDistribution": {
          "type": "linear"
        },
        "axisCenteredZero": false,
        "hideFrom": {
          "tooltip": false,
          "viz": false,
          "legend": false
        },
        "thresholdsStyle": {
          "mode": "off"
        }
      },
      "color": {
        "mode": "palette-classic"
      },
      "mappings": [],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "color": "green",
            "value": null
          },
          {
            "color": "red",
            "value": 80
          }
        ]
      },
      "unit": "percent",
      "min": 0,
      "max": 100
    },
    "overrides": []
  },
  "pluginVersion": "12.4.0",
  "targets": [
    {
      "refId": "A",
      "editorMode": "code",
      "rawQuery": true,
      "format": "time_series",
      "rawSql": "SELECT\n  time_bucket(make_interval(secs => ($__interval_ms / 1000)::int), tr.ts) AS \"time\",\n  avg(tr.value) AS \"value\",\n  p.external_id AS \"metric\"\nFROM timeseries_readings tr\nJOIN points p ON p.id = tr.point_id\nWHERE $__timeFilter(tr.ts)\n  AND p.site_id::text IN (${site:sqlstring})\n  AND p.external_id IN ('cloud_pct')\nGROUP BY 1, 3\nORDER BY 1, 3;"
    }
  ],
  "datasource": {
    "uid": "openfdd_timescale"
  },
  "options": {
    "tooltip": {
      "mode": "single",
      "sort": "none",
      "hideZeros": false
    },
    "legend": {
      "showLegend": true,
      "displayMode": "list",
      "placement": "bottom",
      "calcs": []
    }
  }
}
```


## Faults

### Fault Definitions

```json
{
  "id": 1,
  "type": "table",
  "title": "Fault Definitions",
  "gridPos": {
    "x": 0,
    "y": 0,
    "h": 10,
    "w": 14
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "align": "auto",
        "footer": {
          "reducers": []
        },
        "cellOptions": {
          "type": "auto"
        },
        "inspect": false,
        "hideFrom": {
          "viz": false
        }
      },
      "mappings": [],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "color": "green",
            "value": null
          },
          {
            "color": "red",
            "value": 80
          }
        ]
      },
      "color": {
        "mode": "thresholds"
      }
    },
    "overrides": []
  },
  "pluginVersion": "12.4.0",
  "targets": [
    {
      "dataset": "openfdd",
      "datasource": {
        "type": "grafana-postgresql-datasource",
        "uid": "openfdd_timescale"
      },
      "editorMode": "code",
      "format": "table",
      "rawQuery": true,
      "rawSql": "SELECT \r\n  fault_id, \r\n  name, \r\n  category, \r\n  severity, \r\n  -- Shows what Brick equipment this rule binds to (e.g., AHU, VAV)\r\n  array_to_string(equipment_types, ', ') AS target_equipment,\r\n  -- Shows the raw JSON of the specific Brick points it needs (e.g., sat, mat)\r\n  inputs AS required_points,\r\n  updated_at\r\nFROM fault_definitions\r\nWHERE $__timeFilter(updated_at)\r\nORDER BY updated_at DESC;",
      "refId": "A",
      "sql": {
        "columns": [
          {
            "parameters": [],
            "type": "function"
          }
        ],
        "groupBy": [
          {
            "property": {
              "type": "string"
            },
            "type": "groupBy"
          }
        ],
        "limit": 50
      }
    }
  ],
  "datasource": {
    "type": "grafana-postgresql-datasource",
    "uid": "openfdd_timescale"
  },
  "options": {
    "showHeader": true,
    "cellHeight": "sm"
  }
}
```

### Fault Definition Count


```json

{
  "id": 2,
  "type": "stat",
  "title": "Fault Definition Count",
  "gridPos": {
    "x": 0,
    "y": 15,
    "h": 15,
    "w": 24
  },
  "fieldConfig": {
    "defaults": {
      "mappings": [],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "color": "green",
            "value": null
          },
          {
            "color": "red",
            "value": 80
          }
        ]
      },
      "color": {
        "mode": "thresholds"
      }
    },
    "overrides": []
  },
  "pluginVersion": "12.4.0",
  "targets": [
    {
      "dataset": "openfdd",
      "datasource": {
        "type": "grafana-postgresql-datasource",
        "uid": "openfdd_timescale"
      },
      "editorMode": "code",
      "format": "table",
      "rawQuery": true,
      "rawSql": "SELECT count(*)::int AS \"Fault definitions\"\r\nFROM fault_definitions;",
      "refId": "A",
      "sql": {
        "columns": [
          {
            "parameters": [],
            "type": "function"
          }
        ],
        "groupBy": [
          {
            "property": {
              "type": "string"
            },
            "type": "groupBy"
          }
        ],
        "limit": 50
      }
    }
  ],
  "datasource": {
    "type": "grafana-postgresql-datasource",
    "uid": "openfdd_timescale"
  },
  "options": {
    "reduceOptions": {
      "values": false,
      "calcs": [
        "lastNotNull"
      ],
      "fields": ""
    },
    "orientation": "auto",
    "textMode": "auto",
    "wideLayout": true,
    "colorMode": "value",
    "graphMode": "area",
    "justifyMode": "auto",
    "showPercentChange": false,
    "percentChangeColorMode": "standard"
  }
}
```