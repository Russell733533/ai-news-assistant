# -*- coding: utf-8 -*-

import os
import feedparser
import requests
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta
import pytz

# --- 1. 配置区域 ---
RSS_FEEDS = {
    "Google News AI (EN)": "https://news.google.com/rss/search?q=Artificial+Intelligence&hl=en-US&gl=US&ceid=US:en",
    "TechCrunch AI (EN)": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "量子位 (中文)": "https://www.qbitai.com/feed/",
    "机器之心 (中文)": "https://www.jiqizhixin.com/rss",
    "MIT Tech Review (EN)": "https://www.technologyreview.com/c/artificial-intelligence/feed/",
    "ArXiv CS.AI (Paper)": "http://arxiv.org/rss/cs.AI"
}

PER_FEED_LIMIT = 5 
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- 2. 功能函数 ---

def get_balanced_articles(feed_urls, limit_per_feed):
    print("🚀 开始从各新闻源均衡获取文章...")
    all_articles = []
    unique_links = set()
    utc = pytz.UTC
    twenty_four_hours_ago = datetime.now(utc) - timedelta(hours=24)
    for name, url in feed_urls.items():
        try:
            feed = feedparser.parse(url)
            print(f"  - 正在处理: {name}")
            count = 0
            for entry in feed.entries:
                if count >= limit_per_feed: break
                published_time = None
                if 'published_parsed' in entry and entry.published_parsed:
                    published_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), utc)
                if published_time and published_time > twenty_four_hours_ago and entry.link not in unique_links:
                    article_data = { 'title': entry.title, 'link': entry.link, 'source': name, 'summary': entry.get('summary', '') }
                    all_articles.append(article_data)
                    unique_links.add(entry.link)
                    count += 1
        except Exception as e:
            print(f"  ❌ 获取 {name} 时出错: {e}")
    print(f"✅ 获取完成，共找到 {len(all_articles)} 条新闻。")
    return all_articles

def get_content_with_playwright(url):
    content = None
    print("    - 启动Playwright浏览器...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"})
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(3000)
            html_content = page.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            main_content = soup.find('article') or soup.find('main')
            if main_content:
                paragraphs = main_content.find_all('p')
            else:
                paragraphs = soup.find_all('p')
            content = "\n".join([p.get_text() for p in paragraphs if p.get_text()])
            browser.close()
            if content: print("    - Playwright 提取成功！")
            else: print("    - Playwright 提取内容为空。")
    except Exception as e:
        print(f"    - Playwright 提取失败: {e}")
    return content[:3000] if content else None

def summarize_with_gemini(content):
    if not content:
        return "无法获取正文，跳过总结。"
    try:
        # *** 决定性的最终修改：强制指定使用 v1 API 版本，不再依赖默认行为 ***
        genai.configure(
            api_key=GEMINI_API_KEY,
            client_options={"api_version": "v1"}
        )
        
        model = genai.GenerativeModel('gemini-pro')
        prompt = f"请用简体中文，用一句话（不超过60字）精准地总结以下新闻或论文摘要的核心内容，不需要任何多余的开头或结尾：\n\n---\n{content}\n---"
        response = model.generate_content(prompt)
        summary = response.text.strip().replace('*', '')
        return summary
    except Exception as e:
        print(f"    - Gemini API调用失败: {e}")
        return "AI总结失败。"

def send_to_feishu(content):
    if not content:
        print("内容为空，不发送消息。")
        return
    headers = {'Content-Type': 'application/json'}
    payload = { "msg_type": "interactive", "card": { "header": { "title": { "tag": "plain_text", "content": f"🔔 今日AI新闻摘要 ({datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')})" }, "template": "blue" }, "elements": [ { "tag": "div", "text": { "tag": "lark_md", "content": content }}, {"tag": "hr"}, { "tag": "note", "elements": [{"tag": "plain_text", "content": "由GitHub Actions + Gemini Pro 驱动"}] } ] } }
    try:
        response = requests.post(FEISHU_WEBHOOK_URL, json=payload, headers=headers)
        if response.status_code == 200 and response.json().get("StatusCode") == 0: print("🎉 成功发送消息到飞书！")
        else: print(f"❌ 发送飞书失败: {response.status_code}, {response.text}")
    except Exception as e: print(f"❌ 发送飞书时发生网络错误: {e}")

# --- 3. 主程序入口 ---
if __name__ == "__main__":
    if not FEISHU_WEBHOOK_URL or not GEMINI_API_KEY:
        print("🚨 错误：未设置 FEISHU_WEBHOOK_URL 或 GEMINI_API_KEY 环境变量！")
        exit()
    articles = get_balanced_articles(RSS_FEEDS, PER_FEED_LIMIT)
    if not articles:
        print("💤 今天没有发现新文章，程序结束。")
        exit()
    print("\n🔍 开始处理每篇文章并生成摘要...")
    summaries = []
    for i, article in enumerate(articles):
        print(f"  - ({i+1}/{len(articles)}) 正在处理: {article['title']}")
        summary = ""
        if 'ArXiv' in article['source'] and article['summary']:
            print("    - 检测到ArXiv链接，直接使用自带摘要。")
            soup = BeautifulSoup(article['summary'], 'html.parser')
            summary = soup.get_text().strip().replace('\n', ' ')
        else:
            content = get_content_with_playwright(article['link'])
            summary = summarize_with_gemini(content)
        formatted_item = ( f"**{article['title']}**\n" f"> **摘要**: {summary}\n" f"来源: {article['source']}\n" f"链接: [{article['link']}]({article['link']})\n" )
        summaries.append(formatted_item)
        time.sleep(1)
    if summaries:
        final_content = "\n---\n\n".join(summaries)
        send_to_feishu(final_content)
    else:
        print("所有文章都未能成功生成摘要，不发送消息。")
    print("\n✅ 所有任务完成！")
