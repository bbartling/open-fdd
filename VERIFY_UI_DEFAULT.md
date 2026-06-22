# Verify default UI

Run:

```powershell
docker compose down
docker compose build --no-cache
docker compose up
```

Open:

```text
http://localhost:8080
```

The default page should show the driver-tree UI without needing `?v=fix2`.

Expected UI:
- Left driver tree: BACnet, Modbus, JSON API, Haystack
- Tabs: Dashboard, SQL FDD, Plots, Haystack, CDL, Wire Sheet
- No Rule Lab tab
- No `/api/haystack/model` requests

Smoke checks:

```powershell
curl.exe -s http://localhost:8080/app.js | findstr /C:"DEFAULT DRIVER TREE BUILD"
curl.exe -s http://localhost:8080/app.js | findstr /C:"Rule Lab"
curl.exe -s http://localhost:8080/app.js | findstr /C:"/api/haystack/model"
```

The first command should print a hit. The last two should print nothing.
