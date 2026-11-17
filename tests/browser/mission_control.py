"""Optional real-browser regression; start make visualize before running."""
import argparse
import copy
import json
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading

from playwright.sync_api import sync_playwright


def check(url, assets_dir=None):
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True,
                                              args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1600, "height": 1100})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("document.querySelector('#commandState').textContent === 'recorded'")
        bundle = page.evaluate("fetch('execution-trace.json').then(r=>r.json())")
        joint = bundle["result"].get("mission_kind") == "joint-axb"
        if joint:
            assert bundle["result"]["status"] == "completed"
            assert bundle["result"]["transport"] == "tcp"
            assert "oslurm.joint_execution" in page.locator("#commandInput").input_value()
            assert bundle["result"]["job_id"] in page.locator("#jobMeta").text_content()
            assert page.locator("#schedulerRateLabel").text_content() == "worker elapsed"
            assert page.locator('[data-card="sat001"] .tag').text_content() == "idle"
        else:
            assert bundle["result"]["autonomy"]["autonomous_decisions"] > 0
        assert page.locator("#satelliteSelect option").count() == 4
        assert all("--" not in text for text in page.locator("#nodeCards .metric b").all_text_contents())
        initial_soc = page.locator('[data-card="sat001"] [data-metric="soc"]').get_attribute("data-value")
        initial_thermal = page.locator('[data-card="sat001"] [data-metric="thermal"]').get_attribute("data-value")
        assert "analytic_power_thermal" in page.locator('[data-card="sat001"] [data-metric="soc"]').get_attribute("title")
        page.locator('[data-view="map"]').click()
        assert page.locator('[data-pointer-mode="rotate"]').is_disabled()
        canvas = page.locator("#orbitCanvas")
        bounds = canvas.bounding_box()
        before = canvas.screenshot()
        assert page.evaluate("""() => {
          const c=document.querySelector('#orbitCanvas'), d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
          const colors=new Set(); for(let i=0;i<d.length;i+=128) colors.add(`${d[i]},${d[i+1]},${d[i+2]}`);
          return colors.size > 80;
        }""")
        # Pick the satellite at its WGS84 subpoint on the full-world map.
        point = page.evaluate("""bundle => {
          const sample=bundle.ephemeris.samples.find(s=>s.node_id==='sat003');
          const p=GroundTrackView.subpoint(sample), c=document.querySelector('#orbitCanvas').getBoundingClientRect();
          const w=c.width-28, h=Math.min(w/2,c.height-168), top=Math.max(92,(c.height-h)/2);
          return {x:c.x+14+(p.lon+180)/360*w, y:c.y+top+(90-p.lat)/180*h};
        }""", bundle)
        page.locator('[data-pointer-mode="select"]').click()
        page.mouse.click(point["x"], point["y"])
        assert page.locator("#satelliteSelect").input_value() == "sat003"
        inspector = page.locator("#orbitalGrid").inner_text()
        page.screenshot(path="/tmp/oslurm-map-initial.png", full_page=True)
        page.clock.install()
        page.locator("#sendCommand").click()
        page.clock.fast_forward(15000)
        assert canvas.screenshot() != before
        assert canvas.bounding_box() == bounds
        assert page.locator("#groundStatus").text_content() == ("n/a" if joint else "disconnected")
        assert page.locator("#orbitalGrid").inner_text() == inspector
        assert page.locator('[data-card="sat001"] [data-metric="soc"]').get_attribute("data-value") != initial_soc
        assert page.locator('[data-card="sat001"] [data-metric="thermal"]').get_attribute("data-value") != initial_thermal
        page.screenshot(path="/tmp/oslurm-map-mid.png", full_page=True)
        if assets_dir:
            assets_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(assets_dir / "oslurm_ground_track.png"), full_page=True)
            page.locator('[data-view="iso"]').click()
            page.mouse.move(bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2)
            for _ in range(14):
                page.mouse.wheel(0, -100)
                page.wait_for_timeout(20)
            page.screenshot(path=str(assets_dir / "oslurm_main.png"), full_page=True)
            page.locator('[data-view="map"]').click()
        page.locator('[data-pointer-mode="pan"]').click()
        page.mouse.move(bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2)
        for _ in range(6):
            page.mouse.wheel(0, -300)
            page.wait_for_timeout(20)
        zoomed = canvas.screenshot()
        page.mouse.down(); page.mouse.move(bounds["x"] + bounds["width"] / 2 + 45, bounds["y"] + bounds["height"] / 2 + 20, steps=4); page.mouse.up()
        assert canvas.screenshot() != zoomed
        page.locator('[data-view="iso"]').click()
        assert not page.locator('[data-pointer-mode="rotate"]').is_disabled()
        assert canvas.screenshot() != zoomed
        page.locator('[data-view="status"]').click()
        assert not canvas.is_visible()
        assert not page.locator("#viewControls").is_visible()
        page.locator('[data-view="map"]').click()
        page.clock.fast_forward(16000)
        assert page.locator("#commandState").text_content() == "complete"
        assert page.locator("#commStatus").text_content() == "complete"
        assert all("SCHEDULER_DECISION" in text for text in page.locator("#eventList .event.blue").all_text_contents())
        page.locator("#resetCommand").click()
        assert page.locator('[data-card="sat001"] [data-metric="soc"]').get_attribute("data-value") == initial_soc
        assert page.locator("#eventList").inner_text() == ""
        for width, height in [(1180, 900), (390, 844)]:
            screen = browser.new_page(viewport={"width": width, "height": height})
            screen.on("pageerror", lambda error: errors.append(str(error)))
            screen.goto(url, wait_until="networkidle")
            screen.locator('[data-view="map"]').click()
            assert screen.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"overflow at {width}"
            assert screen.locator("#orbitCanvas").bounding_box()["height"] > 100
            title = screen.locator(".orbit-panel > .panel-title").bounding_box()
            orbit = screen.locator(".orbit-body").bounding_box()
            assert title["y"] + title["height"] <= orbit["y"] + 1, f"header overlap at {width}"
            assert screen.locator("#eventList").bounding_box()["height"] >= 100
            screen.screenshot(path=f"/tmp/oslurm-map-{width}.png", full_page=True)
        missing = copy.deepcopy(bundle)
        missing["events"] = [event for event in missing["events"] if not (
            event["header"]["event_type"] == "NODE_OPERATING_SNAPSHOT" and event["header"]["node_id"] == "sat004")]
        missing_page = browser.new_page()
        missing_page.route("**/execution-trace.json", lambda route: route.fulfill(json=missing))
        missing_page.goto(url, wait_until="networkidle")
        assert missing_page.locator('[data-card="sat004"] [data-metric="soc"] b').text_content() == "--"
        assert missing_page.locator('[data-card="sat001"] [data-metric="soc"] b').text_content() != "--"
        assert not errors, errors
        browser.close()
        return {"mission": bundle["result"].get("mission_kind", "orbit"), "autonomy": bundle["result"].get("autonomy"), "map": "selection/animation/zoom/pan passed",
                "telemetry": "initial/evolution/reset/missing-data passed", "browser_errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8081/")
    parser.add_argument("--assets-dir", type=Path)
    parser.add_argument("--serve", action="store_true", help="Start a temporary local HTTP server for regression")
    args = parser.parse_args()
    if args.serve:
        handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).resolve().parents[2] / "docs/visualization"))
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                print(json.dumps(check(f"http://127.0.0.1:{server.server_port}/", args.assets_dir)))
            finally:
                server.shutdown()
                thread.join()
    else:
        print(json.dumps(check(args.url, args.assets_dir)))
