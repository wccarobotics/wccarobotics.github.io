"""
FTC Score Card Generator (Browser-based)

Screenshots the official FTC events website match detail pages using Playwright,
cleans up the UI, and composites onto a 1920x1080 frame with a blue gradient
background matching the FTC branding.

Usage:
    # Single scorecard from a URL
    python generate_scorecard_browser.py --url https://ftc-events.firstinspires.org/2025/USARLRAS/qualifications/1 --output scorecard_q1.png

    # Generate all scorecards for an event
    python generate_scorecard_browser.py --event-code USARLRAS --season 2025 --output-dir scorecards/

    # Generate rankings page
    python generate_scorecard_browser.py --url https://ftc-events.firstinspires.org/2025/USARLRAS/rankings --output rankings.png

Requirements:
    pip install playwright Pillow numpy
    python -m playwright install chromium
"""

import argparse
import io
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

# Output dimensions
WIDTH, HEIGHT = 1920, 1080

# Blue gradient colors matching FTC site: #003974 -> #6CC2C9 -> #003974
GRADIENT_LEFT = (0, 57, 116)
GRADIENT_MID = (108, 194, 201)
GRADIENT_RIGHT = (0, 57, 116)

# Viewport size for Playwright browser
VIEWPORT_WIDTH = 1400
VIEWPORT_HEIGHT = 900

# JS cleanup shared across all page types
JS_CLEANUP_BASE = """() => {
    // Cookie banner
    document.querySelectorAll('[class*="cookie"], [class*="consent"], [id*="cookie"]').forEach(el => el.remove());
    // Nav bar
    const nav = document.querySelector('nav, .navbar, header');
    if (nav) nav.remove();
    // Color strip
    document.querySelectorAll('.color-strip, [class*="color-strip"]').forEach(el => el.remove());
    // Footer
    const footer = document.querySelector('footer');
    if (footer) footer.remove();
    // Bottom logos
    document.querySelectorAll('.bottom-logo, [class*="bottom-logo"]').forEach(el => el.remove());
    document.querySelectorAll('img[alt="Game Logo"]').forEach(el => {
        const parent = el.closest('div');
        if (parent) parent.remove(); else el.remove();
    });

    // Style the body
    document.body.style.background = 'white';
    document.body.style.margin = '0';
    document.body.style.padding = '0';

    // Style h1
    const h1 = document.querySelector('h1');
    if (h1) {
        h1.style.fontSize = '38px';
        h1.style.color = 'black';
        h1.style.textAlign = 'center';
        h1.style.margin = '20px 0 5px 0';
    }

    // Style event subtitle
    const subtitle = document.querySelector('h1 + .event-subtitle, h1 ~ .text-muted');
    if (subtitle) {
        subtitle.style.fontSize = '22px';
        subtitle.style.color = '#666';
        subtitle.style.textAlign = 'center';
    }

    // Fix scrolling team names (FTC website JS duplicates text for marquee)
    document.querySelectorAll('.deep-team-name-scrolling').forEach(scrollSpan => {
        const inner = scrollSpan.closest('.deep-team-name-inner');
        if (inner) {
            let text = scrollSpan.textContent.trim();
            const half = Math.ceil(text.length / 2);
            const firstHalf = text.substring(0, half).trim();
            const secondHalf = text.substring(half).trim();
            if (firstHalf === secondHalf) text = firstHalf;
            inner.innerHTML = text;
            inner.style.whiteSpace = 'normal';
            inner.style.overflow = 'visible';
            inner.style.animation = 'none';
        }
    });
}"""

# Additional JS for match detail pages (scorecard)
JS_CLEANUP_SCORECARD = """() => {
    const sd = document.querySelector('.scoredetail-container');
    if (sd) {
        // Remove "Score Comparison" button row (class: flex-center mb-3 row)
        sd.querySelectorAll('.flex-center').forEach(el => el.remove());
        // Remove hidden comparison div
        sd.querySelectorAll('.d-none').forEach(el => {
            if (el.closest('.scoredetail-container') === sd && el.classList.contains('row')) {
                el.remove();
            }
        });
        // Remove Breakdown/Details tabs and tab content
        sd.querySelectorAll('.nav-tabs, .tab-content').forEach(el => el.remove());
        // Remove the breakdown row container
        Array.from(sd.children).forEach(ch => {
            if (ch.tagName === 'DIV' && ch.classList.contains('row') &&
                ch.textContent.includes('Breakdown')) {
                ch.remove();
            }
        });
    }
    // Remove navigation arrows (> >>) from the score banner yellow columns
    document.querySelectorAll('.deep-scoreboard-totalpoints-yellow').forEach(el => {
        el.innerHTML = '';
    });
    // Remove any remaining navigation links
    document.querySelectorAll('a').forEach(el => {
        if (el.textContent.includes('Return to')) el.remove();
    });
    // Remove Jump button
    document.querySelectorAll('button').forEach(btn => {
        if (btn.textContent.includes('Jump')) btn.remove();
    });
}"""

# Additional JS for rankings page
JS_CLEANUP_RANKINGS = """() => {
    // Remove "Return to" links
    document.querySelectorAll('a').forEach(el => {
        if (el.textContent.includes('Return to')) el.remove();
    });
    // Remove Export CSV button and Jump button
    document.querySelectorAll('button').forEach(btn => {
        if (btn.textContent.includes('Export CSV') || btn.textContent.includes('Jump')) {
            btn.remove();
        }
    });
    // Remove sort indicators (background-image GIFs on th elements)
    const style = document.createElement('style');
    style.textContent = `
        th.tablesorter-header {
            background-image: none !important;
            padding-right: 8px !important;
            cursor: default !important;
        }
    `;
    document.head.appendChild(style);
}"""


def make_gradient(width, height):
    """Create a blue gradient background image matching the FTC site branding."""
    canvas = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(canvas)
    half = width // 2
    for x in range(width):
        if x < half:
            t = x / half
            color = tuple(int(GRADIENT_LEFT[i] + (GRADIENT_MID[i] - GRADIENT_LEFT[i]) * t) for i in range(3))
        else:
            t = (x - half) / half
            color = tuple(int(GRADIENT_MID[i] + (GRADIENT_RIGHT[i] - GRADIENT_MID[i]) * t) for i in range(3))
        draw.line([(x, 0), (x, height - 1)], fill=color)
    return canvas


def detect_page_type(url):
    """Detect whether the URL is a scorecard, rankings, or other page."""
    if '/rankings' in url:
        return 'rankings'
    elif '/qualifications/' in url or '/playoff/' in url:
        return 'scorecard'
    else:
        return 'other'


def screenshot_page(url, page_type='auto'):
    """Take a cleaned-up screenshot of an FTC events page.

    Returns a PIL Image of the cropped and cleaned content.
    """
    if page_type == 'auto':
        page_type = detect_page_type(url)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': VIEWPORT_WIDTH, 'height': VIEWPORT_HEIGHT})
        page.goto(url, wait_until='networkidle')
        # Wait for JS animations (team name scrolling) to initialize
        page.wait_for_timeout(3000)

        # Apply base cleanup
        page.evaluate(JS_CLEANUP_BASE)

        # Apply page-type-specific cleanup
        if page_type == 'scorecard':
            page.evaluate(JS_CLEANUP_SCORECARD)
        elif page_type == 'rankings':
            page.evaluate(JS_CLEANUP_RANKINGS)

        page.wait_for_timeout(500)
        screenshot_bytes = page.screenshot(full_page=True)
        browser.close()

    return Image.open(io.BytesIO(screenshot_bytes))


def crop_content(img):
    """Crop whitespace from top and bottom of screenshot."""
    arr = np.array(img)
    row_has_content = np.any(arr < 240, axis=(1, 2))
    content_rows = np.where(row_has_content)[0]
    if len(content_rows) == 0:
        return img
    top = max(0, content_rows[0] - 10)
    bottom = min(img.height, content_rows[-1] + 10)
    return img.crop((0, top, img.width, bottom))


def composite_on_gradient(content_img, output_width=WIDTH, output_height=HEIGHT):
    """Scale content to fit width, center on gradient background."""
    scale = output_width / content_img.width
    new_h = int(content_img.height * scale)

    # If scaled content is taller than canvas, reduce scale to fit
    if new_h > output_height:
        scale = output_height / content_img.height
        new_w = int(content_img.width * scale)
        new_h = output_height
    else:
        new_w = output_width

    scaled = content_img.resize((new_w, new_h), Image.LANCZOS)

    canvas = make_gradient(output_width, output_height)
    x_offset = (output_width - new_w) // 2
    y_offset = (output_height - new_h) // 2
    canvas.paste(scaled, (x_offset, y_offset))

    return canvas


def generate_scorecard(url, output_path, page_type='auto'):
    """Generate a single 1920x1080 scorecard/rankings image from a URL."""
    print(f"Screenshotting: {url}")
    raw = screenshot_page(url, page_type)
    print(f"  Raw screenshot: {raw.size}")

    cropped = crop_content(raw)
    print(f"  Cropped: {cropped.size}")

    final = composite_on_gradient(cropped)
    final.save(output_path, quality=95)
    print(f"  Saved: {output_path}")
    return final


def generate_event_scorecards(event_code, season, output_dir, qual_matches=None, playoff_series=None):
    """Generate all scorecards for an FTC event.

    Args:
        event_code: FTC event code (e.g., 'USARLRAS')
        season: Season year (e.g., '2025')
        output_dir: Directory to save PNGs
        qual_matches: List of qualification match numbers, or None for all 1-10
        playoff_series: List of (series, match) tuples, or None to auto-detect
    """
    os.makedirs(output_dir, exist_ok=True)
    base_url = f"https://ftc-events.firstinspires.org/{season}/{event_code}"

    # Qualification matches
    if qual_matches is None:
        qual_matches = list(range(1, 11))

    for n in qual_matches:
        url = f"{base_url}/qualifications/{n}"
        output = os.path.join(output_dir, f"scorecard_q{n}.png")
        try:
            generate_scorecard(url, output)
        except Exception as e:
            print(f"  ERROR on Q{n}: {e}")

    # Playoff matches
    if playoff_series is None:
        playoff_series = [(1, 1), (1, 2), (1, 3)]

    for series, match in playoff_series:
        url = f"{base_url}/playoff/{series}/{match}"
        output = os.path.join(output_dir, f"scorecard_f{series}_{match}.png")
        try:
            generate_scorecard(url, output)
        except Exception as e:
            print(f"  ERROR on F{series}-{match}: {e}")

    # Rankings
    rankings_url = f"{base_url}/rankings"
    rankings_output = os.path.join(output_dir, "rankings.png")
    try:
        generate_scorecard(rankings_url, rankings_output, page_type='rankings')
    except Exception as e:
        print(f"  ERROR on rankings: {e}")

    print(f"\nAll scorecards saved to {output_dir}/")


def main():
    parser = argparse.ArgumentParser(
        description='Generate FTC scorecard images from the official FTC events website.'
    )
    parser.add_argument('--url', help='URL of a single FTC events page to screenshot')
    parser.add_argument('--output', '-o', help='Output PNG path (for single URL mode)')
    parser.add_argument('--event-code', help='FTC event code for batch generation (e.g., USARLRAS)')
    parser.add_argument('--season', help='FTC season year (e.g., 2025)')
    parser.add_argument('--output-dir', default='scorecards', help='Output directory for batch mode (default: scorecards/)')
    parser.add_argument('--qual-matches', help='Comma-separated qualification match numbers (default: 1-10)')
    parser.add_argument('--page-type', choices=['auto', 'scorecard', 'rankings'], default='auto',
                        help='Page type hint (default: auto-detect from URL)')

    args = parser.parse_args()

    if args.url:
        output = args.output or 'scorecard.png'
        generate_scorecard(args.url, output, args.page_type)
    elif args.event_code and args.season:
        qual = None
        if args.qual_matches:
            qual = [int(x.strip()) for x in args.qual_matches.split(',')]
        generate_event_scorecards(args.event_code, args.season, args.output_dir, qual_matches=qual)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
