---
title: BACnet
nav_order: 6
has_children: true
---

# BACnet

BACnet is the **default data driver** for Open-FDD. Discovery, [diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server), and the BACnet scraper are documented here. **Swagger (diy-bacnet-server):** http://localhost:8080/docs

---

## Setup (do this before the platform scrapes data)

1. **Run BACnet discovery first** — Before starting diy-bacnet-server or the Open-FDD stack, run the discovery script. Only one BACnet process can bind to port 47808 (UDP) on the OS; discovery uses that port, so run it while no other BACnet application is running. See [BACnet overview → Discovery first, then curate the CSV](bacnet/overview#discovery-first-then-curate-the-csv).
2. **Curate the discovery CSV** — The script discovers **every** point on the BACnet network. You must remove rows for points that are not needed for FDD and HVAC health. Typically only a small subset of points (on the order of ~20% for a typical HVAC system) are needed; scraping every point is unnecessary and increases OT load. See [Security → Throttling](security#2-outbound-otbuilding-network-is-paced).
3. **Save the CSV as the driver config** — The BACnet scraper reads `config/bacnet_discovered.csv` (or the path you set) as its list of points to poll. Use the curated file.
4. **Then start the platform** — Run `./scripts/bootstrap.sh` (or start diy-bacnet-server and bacnet-scraper). The scraper will use the CSV to pull only the points you kept.
