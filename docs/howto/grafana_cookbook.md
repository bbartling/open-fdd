---
title: Grafana SQL cookbook
parent: How-to Guides
nav_order: 40
---


# Grafana SQL cookbook — 

## BACnet data

Insert Snip here

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