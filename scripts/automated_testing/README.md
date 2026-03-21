# Automated testing (notes)

## Windows: Python deps (PowerShell)

From **repo root** — install everything these scripts expect (Selenium, httpx, optional TTL checks):

```powershell
pip install -r scripts/automated_testing/requirements-e2e.txt
```

Or equivalent one-liner (quotes matter on Windows):

```powershell
pip install "selenium>=4" "webdriver-manager>=4" httpx "rdflib>=7,<8" "pyparsing>=2.1,<3.2"
```

- **Chrome** (or Chromium) must be installed; `webdriver-manager` fetches a matching ChromeDriver.
- **`2_sparql_crud_and_frontend_test.py`** only needs the file above for the client; if your **API** on `:8000` does SPARQL, that server’s venv also needs **`pyparsing<3.2`** with rdflib 7.x (same pin) or you get `Param.postParse2 … tokenList` errors.

## Run examples (repo root)

```powershell
python scripts/automated_testing/1_e2e_frontend_selenium.py --help
python scripts/automated_testing/2_sparql_crud_and_frontend_test.py --help
```

Paths use forward slashes; they work in PowerShell.

**Scripts on Windows, Open FDD on a Linux box:** pass the **server** IP/hostname to `--frontend-url` and `--api-url` (e.g. `http://192.168.204.16` and `http://192.168.204.16:8000`). `localhost` would mean your PC, not the server. See the Usage block in `2_sparql_crud_and_frontend_test.py`.
