#!/usr/bin/env python3
"""
Remove phantom BACnet device 34567 from Open-Meteo (Weather-Station) points in data_model.ttl.

The scraper builds its device list from the KG/DB. Those points had bacnet://34567 refs but no
<bacnet://34567> Device block, so reads targeted a non-existent device. Open-Meteo rows should
match other web-weather points: ref:TimeseriesReference only, ofdd:polling false, no BACnet triples.

Usage (from repo root):
  python tools/fix_open_meteo_points_in_ttl.py config/data_model.ttl
Writes in place; pass --dry-run to print diff only.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

FIX_FETCH_OK_OLD = """\
:pt_3d54a63f_6372_471c_b341_cd50fa5a97fc a brick:Point ;
    rdfs:label "web-weather-fetch-ok" ;
    ofdd:bacnetDeviceId "34567" ;
    ofdd:objectIdentifier "binary-value,1" ;
    ofdd:polling false ;
    brick:isPointOf :eq_2fd81252_78b6_45da_b4de_d522277eea45 ;
    ref:hasExternalReference [ a ref:BACnetReference ;
            bacnet:object-identifier "binary-value,1" ;
            bacnet:object-name "web-weather-fetch-ok" ;
            bacnet:objectOf <bacnet://34567> ;
            brick:BACnetURI "bacnet://34567/binary-value,1/present-value" ],
        [ a ref:TimeseriesReference ;
            ref:hasTimeseriesId "web-weather-fetch-ok" ;
            ref:storedAt "postgresql://db:5432/openfdd/timeseries_readings" ] .
"""

FIX_FETCH_OK_NEW = """\
:pt_3d54a63f_6372_471c_b341_cd50fa5a97fc a brick:Point ;
    rdfs:label "web-weather-fetch-ok" ;
    ofdd:polling false ;
    brick:isPointOf :eq_2fd81252_78b6_45da_b4de_d522277eea45 ;
    ref:hasExternalReference [ a ref:TimeseriesReference ;
            ref:hasTimeseriesId "web-weather-fetch-ok" ;
            ref:storedAt "postgresql://db:5432/openfdd/timeseries_readings" ] .
"""

DEW_OLD = """\
:pt_70db4e0a_1895_4b28_a12b_325743f0ad2f a brick:Outside_Air_Dewpoint_Sensor ;
    rdfs:label "web-weather-dewpoint-temp" ;
    ofdd:bacnetDeviceId "34567" ;
    ofdd:mapsToRuleInput "dewpoint" ;
    ofdd:objectIdentifier "analog-value,2" ;
    ofdd:polling true ;
    ofdd:unit "degF" ;
    brick:isPointOf :eq_2fd81252_78b6_45da_b4de_d522277eea45 ;
    ref:hasExternalReference [ a ref:BACnetReference ;
            bacnet:object-identifier "analog-value,2" ;
            bacnet:object-name "web-weather-dewpoint-temp" ;
            bacnet:objectOf <bacnet://34567> ;
            brick:BACnetURI "bacnet://34567/analog-value,2/present-value" ],
        [ a ref:TimeseriesReference ;
            ref:hasTimeseriesId "web-weather-dewpoint-temp" ;
            ref:storedAt "postgresql://db:5432/openfdd/timeseries_readings" ] .
"""

DEW_NEW = """\
:pt_70db4e0a_1895_4b28_a12b_325743f0ad2f a brick:Outside_Air_Dewpoint_Sensor ;
    rdfs:label "web-weather-dewpoint-temp" ;
    ofdd:mapsToRuleInput "dewpoint" ;
    ofdd:polling false ;
    ofdd:unit "degF" ;
    brick:isPointOf :eq_2fd81252_78b6_45da_b4de_d522277eea45 ;
    ref:hasExternalReference [ a ref:TimeseriesReference ;
            ref:hasTimeseriesId "web-weather-dewpoint-temp" ;
            ref:storedAt "postgresql://db:5432/openfdd/timeseries_readings" ] .
"""

DRY_OLD = """\
:pt_9c94b4df_4541_4a96_ba1a_e31d05ed8070 a brick:Outside_Air_Temperature_Sensor ;
    rdfs:label "web-weather-drybulb-temp" ;
    ofdd:bacnetDeviceId "34567" ;
    ofdd:mapsToRuleInput "oat" ;
    ofdd:objectIdentifier "analog-value,1" ;
    ofdd:polling true ;
    ofdd:unit "degF" ;
    brick:isPointOf :eq_2fd81252_78b6_45da_b4de_d522277eea45 ;
    ref:hasExternalReference [ a ref:BACnetReference ;
            bacnet:object-identifier "analog-value,1" ;
            bacnet:object-name "web-weather-drybulb-temp" ;
            bacnet:objectOf <bacnet://34567> ;
            brick:BACnetURI "bacnet://34567/analog-value,1/present-value" ],
        [ a ref:TimeseriesReference ;
            ref:hasTimeseriesId "web-weather-drybulb-temp" ;
            ref:storedAt "postgresql://db:5432/openfdd/timeseries_readings" ] .
"""

DRY_NEW = """\
:pt_9c94b4df_4541_4a96_ba1a_e31d05ed8070 a brick:Outside_Air_Temperature_Sensor ;
    rdfs:label "web-weather-drybulb-temp" ;
    ofdd:mapsToRuleInput "oat" ;
    ofdd:polling false ;
    ofdd:unit "degF" ;
    brick:isPointOf :eq_2fd81252_78b6_45da_b4de_d522277eea45 ;
    ref:hasExternalReference [ a ref:TimeseriesReference ;
            ref:hasTimeseriesId "web-weather-drybulb-temp" ;
            ref:storedAt "postgresql://db:5432/openfdd/timeseries_readings" ] .
"""

RH_OLD = """\
:pt_cef369bd_c274_4fdc_89fc_986fcb6deff5 a brick:Outside_Air_Humidity_Sensor ;
    rdfs:label "web-weather-relative-humidity" ;
    ofdd:bacnetDeviceId "34567" ;
    ofdd:mapsToRuleInput "humidity" ;
    ofdd:objectIdentifier "analog-value,3" ;
    ofdd:polling true ;
    ofdd:unit "%" ;
    brick:isPointOf :eq_2fd81252_78b6_45da_b4de_d522277eea45 ;
    ref:hasExternalReference [ a ref:BACnetReference ;
            bacnet:object-identifier "analog-value,3" ;
            bacnet:object-name "web-weather-relative-humidity" ;
            bacnet:objectOf <bacnet://34567> ;
            brick:BACnetURI "bacnet://34567/analog-value,3/present-value" ],
        [ a ref:TimeseriesReference ;
            ref:hasTimeseriesId "web-weather-relative-humidity" ;
            ref:storedAt "postgresql://db:5432/openfdd/timeseries_readings" ] .
"""

RH_NEW = """\
:pt_cef369bd_c274_4fdc_89fc_986fcb6deff5 a brick:Outside_Air_Humidity_Sensor ;
    rdfs:label "web-weather-relative-humidity" ;
    ofdd:mapsToRuleInput "humidity" ;
    ofdd:polling false ;
    ofdd:unit "%" ;
    brick:isPointOf :eq_2fd81252_78b6_45da_b4de_d522277eea45 ;
    ref:hasExternalReference [ a ref:TimeseriesReference ;
            ref:hasTimeseriesId "web-weather-relative-humidity" ;
            ref:storedAt "postgresql://db:5432/openfdd/timeseries_readings" ] .
"""

PAIRS = [
    (FIX_FETCH_OK_OLD, FIX_FETCH_OK_NEW),
    (DEW_OLD, DEW_NEW),
    (DRY_OLD, DRY_NEW),
    (RH_OLD, RH_NEW),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ttl", type=Path, default=Path("config/data_model.ttl"), nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    path: Path = args.ttl
    text = path.read_text(encoding="utf-8")
    orig = text
    for old, new in PAIRS:
        if old not in text:
            print(f"Skip or already patched (block not found): {old.splitlines()[0]}", file=sys.stderr)
            continue
        text = text.replace(old, new, 1)
    if text == orig:
        print("No changes applied.", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"Would update {path} ({len(orig)} -> {len(text)} chars)", file=sys.stderr)
        diff = difflib.unified_diff(
            orig.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile=f"{path}.orig",
            tofile=str(path),
        )
        sys.stdout.writelines(diff)
        return 0
    path.write_text(text, encoding="utf-8")
    print(f"Updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
