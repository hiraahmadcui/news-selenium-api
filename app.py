import os
import re
from urllib.parse import quote_plus

from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from summa import summarizer

app = Flask(__name__)

# ============ YOUR DETAILS ============
REGISTRATION = os.environ.get("REGISTRATION", "50")
NEWS_SOURCE = os.environ.get("NEWS_SOURCE", "Deutsche Welle")
SEARCH_URL = "https://www.dw.com/search/?languageCode=en&item={kw}&contentType=ARTICLE"
ARTICLE_RE = re.compile(r"dw\.com/.+/a-\d+")
# ======================================


def create_driver():
    options = Options()
    # --- CORE DOCKER FLAGS ---
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # --- FIXES FOR CONNECTION ISSUES ---
    options.add_argument("--no-proxy-server")
    options.add_argument("--ignore-certificate-errors")
    
    # --- FAKE USER AGENT (Prevents site from blocking headless browser) ---
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    options.binary_location = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
    service = Service(executable_path=os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver"))
    return webdriver.Chrome(service=service, options=options)


def search_first_result(keyword):
    url = SEARCH_URL.format(kw=quote_plus(keyword))
    driver = create_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "a")))

        def first_article_href(d):
            for a in d.find_elements(By.TAG_NAME, "a"):
                href = a.get_attribute("href") or ""
                if ARTICLE_RE.search(href):
                    return href
            return False

        WebDriverWait(driver, 25).until(first_article_href)
        return first_article_href(driver)
    finally:
        driver.quit()


def scrape_and_summarize(article_url):
    driver = create_driver()
    try:
        driver.get(article_url)
        WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "p")))
        html = driver.page_source
    finally:
        driver.quit()

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "figure"]):
        tag.decompose()

    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = " ".join(p for p in paras if len(p.split()) > 8)
    if not text:
        text = " ".join(p for p in paras if p)
    if not text:
        return "No article text could be extracted."

    summary = summarizer.summarize(text, ratio=0.2, language="english")
    return summary if summary else text[:600]


@app.route("/")
def index():
    return (
        "<h1>Registration: {}</h1>"
        "<p>News Source: {}</p>"
        "<p>API: <code>/get?keyword=technology</code></p>"
    ).format(REGISTRATION, NEWS_SOURCE)


@app.route("/get", methods=["GET"])
def get_news():
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "Missing query parameter: keyword"}), 400
    try:
        article_url = search_first_result(keyword)
        summary = scrape_and_summarize(article_url)
        return jsonify({
            "registration": REGISTRATION,
            "newssource": NEWS_SOURCE,
            "keyword": keyword,
            "url": article_url,
            "summary": summary,
        })
    except Exception as e:
        return jsonify({"error": str(e), "keyword": keyword}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000)