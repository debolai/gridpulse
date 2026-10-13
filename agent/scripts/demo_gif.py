"""Record docs/assets/demo.gif: one question through the Streamlit UI, frame by frame.

Run with `make demo-gif` (needs `make up-lake`, `make semantic-api`, `make agent-api` and
`make agent-ui` running). Drives the locally installed Google Chrome with Playwright, so no
browser download; Pillow stitches the screenshots into a GIF.
"""

import io
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

UI = "http://localhost:8501"
QUESTION = "Daily demand for PJM in the first week of October 2026"
OUT = Path(__file__).resolve().parents[2] / "docs" / "assets" / "demo.gif"
WIDTH = 960  # GIF width; screenshots are taken at 1280 and scaled down


def main() -> None:
    frames: list[tuple[Image.Image, int]] = []  # (image, milliseconds on screen)

    def snap(page, ms: int) -> None:
        img = Image.open(io.BytesIO(page.screenshot()))
        img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)
        frames.append((img.convert("RGB"), ms))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 860})
        page.goto(UI)
        box = page.get_by_label("Ask about U.S. grid demand, forecasts or data quality")
        box.wait_for(timeout=60_000)
        snap(page, 1500)
        for i in range(0, len(QUESTION), 6):  # typing, a few characters per frame
            box.fill(QUESTION[: i + 6])
            snap(page, 120)
        box.press("Enter")
        page.get_by_text("Planning a metric request").wait_for(timeout=10_000)
        snap(page, 1200)
        page.get_by_text("numbers verified").wait_for(timeout=180_000)
        page.wait_for_timeout(1500)  # let the chart finish drawing
        snap(page, 4000)
        chart = page.locator(
            "[data-testid='stVegaLiteChart'], [data-testid='stArrowVegaLiteChart']"
        )
        chart.first.scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        snap(page, 3500)
        page.get_by_text("Metric request").click()
        page.wait_for_timeout(800)
        page.get_by_text("Metric request").scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        snap(page, 4000)
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    images = [img.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for img, _ in frames]
    images[0].save(
        OUT,
        save_all=True,
        append_images=images[1:],
        duration=[ms for _, ms in frames],
        loop=0,
        optimize=True,
    )
    print(f"{OUT.relative_to(Path.cwd())}: {len(frames)} frames, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    sys.exit(main())
