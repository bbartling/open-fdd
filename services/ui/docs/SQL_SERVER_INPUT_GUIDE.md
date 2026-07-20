# SQL Server input (optional)

SQL in App 19 is **read-only input** into pandas — not a production FDD engine.

## Install

```powershell
pip install -e ".[sqlserver]"
```

Requires **ODBC Driver 18 for SQL Server** on the host.

## Streamlit sidebar

Choose **SQL Server**, enter server/database, username/password (or trusted connection), and a `SELECT` query.

## Streamlit secrets example

```toml
[sqlserver]
server = "myserver.database.windows.net"
database = "historian"
username = "reader"
password = "..."
trusted_connection = false
row_limit = 50000
```

## Safety

- Only `SELECT` allowed
- Rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `MERGE`, `CREATE`, `EXEC`
- Row limit applied when query has no `TOP`/`LIMIT`
- Passwords are masked in UI; never logged

## Trusted connection

Enable **Trusted connection** for Windows integrated auth (no username/password).
