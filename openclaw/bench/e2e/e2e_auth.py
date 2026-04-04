"""Shared Phase-1 app login for Selenium E2E (Open-FDD /login → sessionStorage token)."""

from __future__ import annotations

import os
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

_PAGE_LOAD_TIMEOUT = 30
_ELEMENT_WAIT = 15


def ensure_app_login_if_needed(driver: webdriver.Chrome, base_url: str) -> None:
    """If the browser is on the login page, submit bootstrap app user credentials from the environment.

    Set in the same .env you pass to one_pass_runner (or the shell):

    - ``OFDD_E2E_USERNAME`` / ``OFDD_E2E_PASSWORD`` (preferred for automation), or
    - ``OFDD_APP_USER`` / ``OFDD_APP_PASSWORD`` (if you keep plaintext password in env).
    """
    url = driver.current_url or ""
    src = driver.page_source or ""
    on_login = "/login" in url or (
        "Sign in with your app user" in src and "Sign in" in src and "Username" in src
    )
    if not on_login:
        return
    user = (os.environ.get("OFDD_E2E_USERNAME") or os.environ.get("OFDD_APP_USER") or "").strip()
    pw = (os.environ.get("OFDD_E2E_PASSWORD") or os.environ.get("OFDD_APP_PASSWORD") or "").strip()
    if not user or not pw:
        raise RuntimeError(
            "UI login required: set OFDD_E2E_USERNAME and OFDD_E2E_PASSWORD in your .env "
            "(or OFDD_APP_USER and OFDD_APP_PASSWORD) to match the bootstrap app user."
        )
    wait = WebDriverWait(driver, _ELEMENT_WAIT)
    user_in = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Username']")))
    pw_in = driver.find_element(By.CSS_SELECTOR, "input[type='password'][placeholder='Password']")
    user_in.clear()
    user_in.send_keys(user)
    pw_in.clear()
    pw_in.send_keys(pw)
    driver.find_element(By.CSS_SELECTOR, 'form[aria-label="Sign in"] button[type="submit"]').click()
    WebDriverWait(driver, _PAGE_LOAD_TIMEOUT).until(lambda d: "/login" not in (d.current_url or ""))
    time.sleep(0.5)
