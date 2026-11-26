"""Capturi de ecran ale interfeței (Chrome headless). python tools/shots.py <url#rută> <out.png> [lățime]"""
import sys
from playwright.sync_api import sync_playwright
url, out = sys.argv[1], sys.argv[2]
w = int(sys.argv[3]) if len(sys.argv) > 3 else 1280
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe")
    pg = b.new_page(viewport={"width": w, "height": 900}, color_scheme="light")
    errs = []
    pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url)
    pg.wait_for_timeout(2500)
    if "#/s/" in url:
        pg.evaluate("const v=document.getElementById('vid'); if(v){v.currentTime=2.0}")
        pg.wait_for_timeout(1200)
    pg.screenshot(path=out, full_page=True)
    print("erori:", errs)
    b.close()
