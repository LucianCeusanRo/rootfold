"""Playwright smoke tests for the operator console served by the app."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect, sync_playwright

REPO = Path(__file__).resolve().parents[1]
IMG = REPO / "docs" / "screenshots"

pytestmark = pytest.mark.ui


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


if not _chromium_available():
    pytest.skip(
        "Playwright Chromium is not installed (uv run playwright install chromium)",
        allow_module_level=True,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_healthy(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = str(exc)
        time.sleep(0.1)
    raise RuntimeError(f"UI test server did not become healthy at {url}: {last}")


@pytest.fixture(scope="module")
def live_url(tmp_path_factory) -> Iterator[str]:
    tmp = tmp_path_factory.mktemp("ui-server")
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(REPO / "src"),
            "ROOTFOLD_DATABASE_URL": f"sqlite:///{tmp / 'ui.db'}",
            "ROOTFOLD_JWT_SECRET": "ui-test-secret-which-is-long-enough-32b",
            "ROOTFOLD_ADMIN_PASSWORD": "changeme",
            "ROOTFOLD_SWEEP_INTERVAL_SECONDS": "0",
            "ROOTFOLD_RECOVERY_SWEEP_SECONDS": "0",
            "ROOTFOLD_LAB_MODE": "true",
            "ROOTFOLD_LOG_LEVEL": "WARNING",
        }
    )
    log_path = tmp / "uvicorn.log"
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "rootfold.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(REPO),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_healthy(url)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def browser_page(live_url: str) -> Iterator[Page]:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            base_url=live_url,
        )
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def _login(page: Page, username: str = "admin", password: str = "changeme") -> None:
    page.goto("/")
    page.get_by_test_id("login-user").fill(username)
    page.get_by_test_id("login-pass").fill(password)
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("incident-list")).to_be_visible(timeout=10_000)


def _reset_lab(live_url: str) -> None:
    token = httpx.post(
        f"{live_url}/api/auth/login",
        json={"username": "admin", "password": "changeme"},
        timeout=10,
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = httpx.post(f"{live_url}/api/lab/reset", headers=headers, timeout=10)
    r.raise_for_status()


@pytest.fixture(autouse=True)
def clean_lab(live_url: str) -> None:
    _reset_lab(live_url)


def test_login_rejects_bad_password(browser_page: Page) -> None:
    page = browser_page
    page.goto("/")
    expect(page.get_by_test_id("login-form")).to_be_visible()
    page.get_by_test_id("login-user").fill("admin")
    page.get_by_test_id("login-pass").fill("wrong-password")
    page.get_by_test_id("login-submit").click()
    expect(page.locator(".flash.err")).to_be_visible()
    expect(page.get_by_test_id("login-form")).to_be_visible()


def test_login_shows_empty_incident_list(browser_page: Page) -> None:
    _login(browser_page)
    expect(browser_page.get_by_test_id("incident-list")).to_contain_text("No incidents")


def test_inject_microwave_gate_blocks_then_escalate(browser_page: Page) -> None:
    page = browser_page
    _login(page)
    page.get_by_test_id("nav-lab").click()
    page.get_by_test_id("btn-inject-microwave_fade").click()
    detail = page.get_by_test_id("incident-detail")
    expect(detail).to_be_visible(timeout=10_000)
    expect(detail).to_contain_text("Microwave")
    expect(detail).to_contain_text("Blast radius")
    expect(page.get_by_test_id("runbook")).to_contain_text("Microwave fade")
    expect(page.locator(".timeline")).to_be_visible()
    expect(page.get_by_test_id("btn-escalate")).to_be_disabled()
    expect(page.get_by_test_id("btn-resolve")).to_be_disabled()

    page.get_by_test_id("gate-impact").select_option("site-down")
    page.get_by_test_id("gate-urgency").select_option("high")
    page.get_by_test_id("gate-check").first.check()
    page.get_by_test_id("gate-notes").fill("Ping failed; maintenance calendar is clear.")
    page.get_by_test_id("gate-save").click()
    expect(page.locator(".flash.ok")).to_contain_text("Quality gate saved")
    expect(page.get_by_test_id("btn-escalate")).to_be_enabled()

    page.get_by_test_id("btn-escalate").click()
    expect(page.get_by_test_id("incident-detail")).to_contain_text("escalated")


def test_handover_requires_incoming_ack(browser_page: Page) -> None:
    page = browser_page
    _login(page)
    page.get_by_test_id("nav-lab").click()
    page.get_by_test_id("btn-inject-fiber_los").click()
    expect(page.get_by_test_id("incident-detail")).to_be_visible(timeout=10_000)

    page.get_by_test_id("nav-handover").click()
    page.get_by_test_id("handover-notes").fill("Fiber to Onești is down; L1 still on it.")
    page.get_by_test_id("handover-close").click()
    expect(page.get_by_test_id("pending-banner")).to_be_visible()
    expect(page.get_by_test_id("pending-handover")).to_be_visible()

    page.locator("#btn-logout").click()
    expect(page.get_by_test_id("login-form")).to_be_visible()
    _login(page, "night", "changeme")
    page.get_by_test_id("nav-handover").click()
    expect(page.get_by_test_id("pending-banner")).to_be_visible()
    page.get_by_test_id("handover-ack-notes").fill("Night shift has the fiber incident.")
    page.get_by_test_id("handover-ack").click()
    expect(page.locator(".flash.ok")).to_contain_text("acknowledged")
    expect(page.get_by_test_id("pending-banner")).to_have_count(0)


def test_leftover_child_stays_visible(browser_page: Page) -> None:
    page = browser_page
    _login(page)
    page.get_by_test_id("nav-lab").click()
    page.get_by_test_id("btn-inject-leftover_sweep").click()
    detail = page.get_by_test_id("incident-detail")
    expect(detail).to_be_visible(timeout=10_000)
    expect(detail).to_contain_text("leftover")
    expect(detail).to_contain_text("Backup")


def test_topology_marks_down_sites(browser_page: Page) -> None:
    page = browser_page
    _login(page)
    page.get_by_test_id("nav-lab").click()
    page.get_by_test_id("btn-inject-microwave_fade").click()
    expect(page.get_by_test_id("incident-detail")).to_be_visible(timeout=10_000)
    page.get_by_test_id("nav-topology").click()
    svg = page.get_by_test_id("topology-map")
    expect(svg).to_be_visible()
    expect(svg.locator('[data-slug="drm"]')).to_be_visible()
    expect(svg.locator('[data-slug="cir-ons-drm-mw"]')).to_be_visible()



def test_runbook_tick_feeds_gate(browser_page: Page) -> None:
    page = browser_page
    _login(page)
    page.get_by_test_id("nav-lab").click()
    page.get_by_test_id("btn-inject-microwave_fade").click()
    expect(page.get_by_test_id("runbook")).to_be_visible(timeout=10_000)
    page.get_by_test_id("runbook-check").first.check()
    expect(page.locator(".flash.ok")).to_contain_text("Check added", timeout=10_000)
    # The same item is now ticked in the L1 gate list.
    expect(page.get_by_test_id("gate-check").first).to_be_checked()


def test_export_shows_dry_run_preview(browser_page: Page) -> None:
    page = browser_page
    _login(page)
    page.get_by_test_id("nav-lab").click()
    page.get_by_test_id("btn-inject-fiber_los").click()
    expect(page.get_by_test_id("export-panel")).to_be_visible(timeout=10_000)
    expect(page.get_by_test_id("btn-export-send")).to_be_disabled()
    page.get_by_test_id("btn-export").click()
    preview = page.get_by_test_id("export-preview")
    expect(preview).to_be_visible()
    expect(preview).to_contain_text("NOC")
    expect(preview).to_contain_text("fields")
    expect(preview).to_contain_text("INC-0001")


def test_reports_page_lists_inventory(browser_page: Page) -> None:
    page = browser_page
    _login(page)
    page.get_by_test_id("nav-reports").click()
    table = page.get_by_test_id("report-table")
    expect(table).to_be_visible(timeout=10_000)
    expect(table).to_contain_text("cir-ons-drm-mw")
    expect(page.get_by_test_id("report-row").first).to_be_visible()
    expect(page.get_by_test_id("btn-report-csv")).to_be_visible()
    expect(page.get_by_test_id("btn-report-print")).to_be_visible()


def test_ui_screenshots(browser_page: Page, live_url: str) -> None:
    """Desktop + mobile captures of the main console views, written to docs/screenshots/."""
    IMG.mkdir(parents=True, exist_ok=True)
    page = browser_page

    def shot(name: str) -> None:
        # Unstick the mobile bottom nav so full-page captures do not paint it mid-scroll.
        page.evaluate(
            """() => {
              for (const sel of ['.bottom-nav', '.topbar']) {
                const el = document.querySelector(sel);
                if (el) {
                  el.dataset.prevPos = el.style.position;
                  el.style.position = 'static';
                }
              }
            }"""
        )
        page.screenshot(path=str(IMG / f"{name}.png"), full_page=True)
        page.evaluate(
            """() => {
              for (const sel of ['.bottom-nav', '.topbar']) {
                const el = document.querySelector(sel);
                if (el) el.style.position = el.dataset.prevPos || '';
              }
            }"""
        )

    # Login, desktop then mobile.
    page.goto("/")
    expect(page.get_by_test_id("login-form")).to_be_visible()
    shot("ui-login-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("ui-login-mobile")
    page.set_viewport_size({"width": 1440, "height": 900})

    _login(page)
    page.get_by_test_id("nav-lab").click()
    expect(page.get_by_test_id("btn-inject-microwave_fade")).to_be_visible()
    shot("ui-lab-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("ui-lab-mobile")
    page.set_viewport_size({"width": 1440, "height": 900})

    page.get_by_test_id("btn-inject-microwave_fade").click()
    expect(page.get_by_test_id("incident-detail")).to_be_visible(timeout=10_000)
    shot("ui-incident-detail-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("ui-incident-detail-mobile")
    page.set_viewport_size({"width": 1440, "height": 900})

    page.get_by_test_id("nav-incidents").click()
    expect(page.get_by_test_id("incident-list")).to_be_visible()
    expect(page.get_by_test_id("incident-row")).to_have_count(1, timeout=10_000)
    shot("ui-incidents-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("ui-incidents-mobile")
    page.set_viewport_size({"width": 1440, "height": 900})

    page.get_by_test_id("nav-topology").click()
    expect(page.get_by_test_id("topology-map")).to_be_visible()
    shot("ui-topology-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("ui-topology-mobile")
    page.set_viewport_size({"width": 1440, "height": 900})

    page.get_by_test_id("nav-handover").click()
    page.get_by_test_id("handover-notes").fill("Microwave last-mile is down; Dărmănești still unreachable.")
    page.get_by_test_id("handover-close").click()
    expect(page.get_by_test_id("pending-banner")).to_be_visible()
    shot("ui-handover-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("ui-handover-mobile")

    # Leftover child, after a clean inject of that scenario.
    page.set_viewport_size({"width": 1440, "height": 900})
    _reset_lab(live_url)
    page.get_by_test_id("nav-lab").click()
    page.get_by_test_id("btn-inject-leftover_sweep").click()
    expect(page.get_by_test_id("incident-detail")).to_contain_text("leftover", timeout=10_000)
    shot("ui-leftover-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("ui-leftover-mobile")

    page.set_viewport_size({"width": 1440, "height": 900})
    _reset_lab(live_url)
    page.get_by_test_id("nav-lab").click()
    page.get_by_test_id("btn-inject-microwave_fade").click()
    expect(page.get_by_test_id("runbook")).to_be_visible(timeout=10_000)
    page.get_by_test_id("btn-export").click()
    expect(page.get_by_test_id("export-preview")).to_be_visible()
    # Scroll the export / runbook area into a full-page capture of the detail.
    shot("ui-export-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("ui-export-mobile")

    page.set_viewport_size({"width": 1440, "height": 900})
    page.get_by_test_id("nav-reports").click()
    expect(page.get_by_test_id("report-table")).to_be_visible(timeout=10_000)
    shot("ui-reports-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("ui-reports-mobile")
