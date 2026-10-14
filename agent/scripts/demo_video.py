"""Record docs/assets/demo.mp4: a two-minute tour, from the scheduler to a verified answer.

Run with `make demo-video`. Needs `make up-orch`, `make docs-site`, `make semantic-api`,
`make agent-api` and `make agent-ui` running (the agent needs a model provider in .env).
Drives the locally installed Google Chrome with Playwright, which records WebM; the ffmpeg
binary bundled with imageio-ffmpeg turns it into a small H.264 MP4 that every browser plays.
Each scene carries a caption, since the video has no sound.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "assets" / "demo.mp4"
SITE = ROOT / "site"
UI = "http://localhost:8501"
AIRFLOW = "http://localhost:8088"
SIZE = {"width": 1280, "height": 800}

CAPTION_JS = """text => {
  let el = document.getElementById('gp-caption');
  if (!el) {
    el = document.createElement('div');
    el.id = 'gp-caption';
    el.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);' +
      'max-width:1000px;padding:12px 20px;border-radius:10px;background:rgba(17,24,39,.88);' +
      'color:#fff;font:500 19px/1.4 system-ui,sans-serif;text-align:center;z-index:2147483647;' +
      'box-shadow:0 4px 16px rgba(0,0,0,.25);pointer-events:none';
    document.body.appendChild(el);
  }
  el.textContent = text;
}"""

TITLE = """<html><body style="margin:0;height:100vh;display:flex;align-items:center;
justify-content:center;background:#0d1117;color:#e6edf3;font-family:system-ui,sans-serif">
<div style="max-width:900px;padding:0 40px">
<div style="font-size:56px;font-weight:700">⚡ GridPulse</div>
<div style="font-size:26px;margin-top:16px;color:#9198a1;line-height:1.4">
Hourly U.S. grid data (EIA-930) and NOAA weather, turned into governed metrics
that people and an LLM assistant can query without writing SQL.</div>
<div style="font-size:20px;margin-top:32px;color:#9198a1">
Airflow 3 · dbt on Iceberg · MetricFlow · LangGraph · Trino locally, Athena + EKS on AWS</div>
</div></body></html>"""


def caption(page: Page, text: str) -> None:
    page.evaluate(CAPTION_JS, text)


def ask(page: Page, question: str, done: str, hold_ms: int) -> None:
    box = page.get_by_placeholder("Ask about U.S. grid data, or answer my question")
    box.click()
    box.press_sequentially(question, delay=35)
    seen = page.get_by_text(done).count()  # earlier replies may already show it
    box.press("Enter")
    page.get_by_text(done).nth(seen).wait_for(timeout=180_000)
    page.wait_for_timeout(1200)  # let the chart finish drawing
    # The newest reply at the top of the screen: its badge, answer and chart.
    page.locator("[data-testid='stChatMessage']").last.evaluate(
        "el => el.scrollIntoView({block: 'start', behavior: 'smooth'})"
    )
    page.wait_for_timeout(hold_ms)


def tour(page: Page) -> None:
    page.set_content(TITLE)
    page.wait_for_timeout(6000)

    page.goto(f"{AIRFLOW}/dags")
    page.get_by_text("eia_hourly").first.wait_for(timeout=30_000)
    caption(page, "Airflow 3 schedules hourly EIA and daily NOAA loads, dbt builds and checks")
    page.wait_for_timeout(5000)
    page.goto(f"{AIRFLOW}/dags/dbt_build")
    page.get_by_text("Last 6 Dag Runs").wait_for(timeout=30_000)
    page.get_by_role("button", name="Graph").first.click()
    page.wait_for_timeout(2000)
    page.get_by_text("+ 35 Tasks").click()  # expand the dbt task group
    page.wait_for_timeout(1500)
    page.locator(".react-flow__controls-fitview").click()
    page.wait_for_timeout(1000)
    caption(
        page, "dbt_build: one task per dbt model and its tests (Cosmos), then the cache refresh"
    )
    page.wait_for_timeout(6000)

    page.goto(UI)
    page.get_by_placeholder("Ask about U.S. grid data, or answer my question").wait_for(
        timeout=60_000
    )
    caption(page, "The assistant plans a metric request; it never writes SQL")
    page.wait_for_timeout(2500)
    ask(page, "Daily demand for PJM in the first week of October 2026", "numbers verified", 3000)
    caption(page, "Every number in the answer is checked against the query result")
    expander = page.get_by_text("Metric request").last
    expander.click()
    page.wait_for_timeout(600)
    expander.evaluate("el => el.scrollIntoView({block: 'start', behavior: 'smooth'})")
    page.wait_for_timeout(5000)

    caption(page, "Follow-ups continue the conversation (memory in Postgres)")
    ask(page, "And for ERCOT?", "numbers verified", 6000)

    caption(page, "Ambiguous? It asks instead of guessing")
    ask(page, "What was peak demand in California in September 2026?", "Which do you mean", 6000)
    caption(page, "The answer to its question completes the request")
    ask(page, "Just CISO", "numbers verified", 6000)

    page.goto((SITE / "dbt" / "index.html").as_uri() + "#!/model/model.gridpulse.fct_grid_hourly")
    page.get_by_text("fct_grid_hourly").first.wait_for(timeout=30_000)
    caption(page, "dbt docs: contracts, tests and descriptions on every mart (published on Pages)")
    page.wait_for_timeout(4500)
    page.locator(".launcher-btn").first.click()
    page.wait_for_timeout(1500)
    page.locator("[ng-click='showExpanded()']").click()
    page.mouse.move(640, 400)  # off the button, so its tooltip goes away
    page.wait_for_timeout(2000)
    caption(page, "Lineage: EIA and NOAA sources → staging → marts → semantic models and metrics")
    page.wait_for_timeout(6500)

    page.goto((SITE / "elementary" / "index.html").as_uri())
    page.get_by_text("Test results breakdown").wait_for(timeout=30_000)
    caption(page, "Elementary: every run's test results and freshness, from the same dbt builds")
    page.wait_for_timeout(7000)
    caption(page, "github.com/debolai/gridpulse · docs: debolai.github.io/gridpulse")
    page.wait_for_timeout(5000)


def main() -> None:
    for path in (SITE / "dbt" / "index.html", SITE / "elementary" / "index.html"):
        if not path.exists():
            sys.exit(f"{path.relative_to(ROOT)} is missing: run make docs-site first")
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport=SIZE, record_video_dir=tmp, record_video_size=SIZE, color_scheme="light"
        )
        page = context.new_page()
        try:
            tour(page)
        finally:
            context.close()  # writes the WebM
            browser.close()
        webm = page.video.path()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(webm),
             "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-an", str(OUT)],
            check=True,
        )  # fmt: skip
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
