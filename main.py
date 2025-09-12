# -*- coding: utf-8 -*-

import os
import feedparser
import requests
import google.generativeai as genai
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta
import pytz

# --- 1. 配置区域 ---
RSS_FEEDS = {
    "Google News AI (EN)": "https://news.google.com/rss/search?q=Artificial+Intelligence&hl=en-US&gl=US&ceid=US:en",
    "TechCrunch AI (EN)": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "MIT Technology Review (EN)": "https://www.technologyreview.com/c/artificial-intelligence/feed/",
    "量子位 (中文)": "https://www.qbitai.com/feed/",
    "机器之心 (中文)": "https://www.jiqizhixin.com/rss",
    "ArXiv CS.AI (Paper)": "http://arxiv.org/rss/cs.AI"
}

FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- 2. 功能函数 ---

def get_unique_articles_from_past_24h(feed_urls):
    """从所有RSS源获取过去24小时内的、不重复的文章列表"""
    print("🚀 开始获取RSS新闻源...")
    unique_articles = {}
    
    utc = pytz.UTC
    twenty_four_hours_ago = datetime.now(utc) - timedelta(hours=24)

    for name, url in feed_urls.items():
        try:
            feed = feedparser.parse(url)
            print(f"  - 正在处理: {name} (共 {len(feed.entries)} 条)")
            for entry in feed.entries:
                published_time = None
                if 'published_parsed' in entry and entry.published_parsed:
                    published_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), utc)
                
                if published_time and published_time > twenty_four_hours_ago:
                    if entry.link not in unique_articles:
                        unique_articles[entry.link] = {
                            'title': entry.title,
                            'link': entry.link,
                            'source': name
                        }
        except Exception as e:
            print(f"  ❌ 获取 {name} 时出错: {e}")
            
    print(f"✅ 获取完成，共找到 {len(unique_articles)} 条不重复的新闻。")
    return list(unique_articles.values())

def get_article_content(url):
    """访问文章链接并提取主要文本内容"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = response.apparent_encoding
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        paragraphs = soup.find_all('p')
        content = "\n".join([p.get_text() for p in paragraphs])
        
        return content[:2500] 
    except Exception as e:
        print(f"    - 抓取正文失败: {url}, 原因: {e}")
        return None

def summarize_with_gemini(content):
    """使用Gemini Pro进行内容总结"""
    if not content:
        return "无法获取正文，跳过总结。"
        
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.0-pro')
        
        prompt = f"请用简体中文，用一句话（不超过50字）精准地总结以下新闻的核心内容，不需要任何多余的开头或结尾：\n\n---\n{content}\n---"
        
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"    - Gemini API调用失败: {e}")
        return "AI总结失败。"

def send_to_feishu(content):
    """将最终格式化的内容通过Webhook发送到飞书"""
    if not content:
        print("内容为空，不发送消息。")
        return

    headers = {'Content-Type': 'application/json'}
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🔔 今日AI新闻摘要 ({datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')})"
                },
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content
                    }
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "由GitHub Actions + Gemini Pro 驱动"
                        }
                    ]
                }
            ]
        }
    }
    
    try:
        response = requests.post(FEISHU_WEBHOOK_URL, json=payload, headers=headers)
        if response.status_code == 200 and response.json().get("StatusCode") == 0:
            print("🎉 成功发送消息到飞书！")
        else:
            print(f"❌ 发送飞书失败: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"❌ 发送飞书时发生网络错误: {e}")

# --- 3. 主程序入口 ---
if __name__ == "__main__":
    
    if not FEISHU_WEBHOOK_URL or not GEMINI_API_KEY:
        print("🚨 错误：未设置 FEISHU_WEBHOOK_URL 或 GEMINI_API_KEY 环境变量！")
        exit()

    # 1. 获取文章
    articles = get_unique_articles_from_past_24h(RSS_FEEDS)
    articles = articles[:30] # 只取最新的30篇文章
    
    if not articles:
        print("💤 今天没有发现新文章，程序结束。")
        exit()
        
    # 2. 循环处理每篇文章并生成摘要
    print("\n🔍 开始处理每篇文章并生成摘要...")
    summaries = []
    for i, article in enumerate(articles):
        print(f"  - ({i+1}/{len(articles)}) 正在处理: {article['title']}")
        
        content = get_article_content(article['link'])
        summary = summarize_with_gemini(content)
        
        formatted_item = (
            f"**{article['title']}**\n"
            f"> **摘要**: {summary}\n"
            f"来源: {article['source']}\n"
            f"链接: [{article['link']}]({article['link']})\n"
        )
        summaries.append(formatted_item)
        
        time.sleep(1)

    # 3. 组合并发送到飞书
    if summaries:
        final_content = "\n---\n\n".join(summaries)
        send_to_feishu(final_content)
    else:
        print("所有文章都未能成功生成摘要，不发送消息。")

    print("\n✅ 所有任务完成！")
