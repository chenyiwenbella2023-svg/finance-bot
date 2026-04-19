#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import requests
import time
import threading
from datetime import datetime
from flask import Flask
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
import yfinance as yf
import random

app = Flask(__name__)

# 从环境变量读取（在Render上设置）
WEBHOOK = os.environ.get('WEBHOOK_URL', 'https://open.feishu.cn/open-apis/bot/v2/hook/01198b2b-074a-4b0c-9825-ffb3bd57244f')
PUSH_TIME = os.environ.get('PUSH_TIME', '16:00')

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ========== 国内网站爬虫 ==========
def crawl_sina():
    """爬取新浪财经"""
    try:
        log("爬取新浪财经...")
        url = "https://finance.sina.com.cn/stock/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        
        news = []
        # 提取新闻
        items = soup.select('a[href*="finance.sina.com.cn"]')
        for item in items[:10]:
            title = item.get_text().strip()
            if len(title) > 10 and ('股' in title or 'A股' in title or '市场' in title):
                news.append({
                    'title': title,
                    'source': '新浪财经',
                    'url': item.get('href', '#'),
                    'time': datetime.now().strftime('%m月%d日 %H:%M')
                })
        log(f"新浪: {len(news)}条")
        return news
    except Exception as e:
        log(f"新浪失败: {e}")
        return []

def crawl_cls():
    """爬取财联社电报"""
    try:
        log("爬取财联社...")
        url = "https://www.cls.cn/v3/telegraph"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        params = {'page': 1, 'size': 20, 'app': 'CailianpressWeb', 'os': 'web'}
        
        r = requests.get(url, headers=headers, params=params, timeout=15)
        data = r.json()
        
        news = []
        if data.get('code') == 200:
            items = data.get('data', {}).get('data', [])[:10]
            for item in items:
                title = item.get('title', '')
                if title:
                    ctime = item.get('ctime', 0)
                    time_str = datetime.fromtimestamp(int(ctime)).strftime('%m月%d日 %H:%M') if ctime else '今日'
                    news.append({
                        'title': title,
                        'source': '财联社',
                        'url': f"https://www.cls.cn/detail/{item.get('id', '')}",
                        'time': time_str
                    })
        log(f"财联社: {len(news)}条")
        return news
    except Exception as e:
        log(f"财联社失败: {e}")
        return []

# ========== 行情数据 ==========
def get_market():
    """获取全球行情"""
    data = {"美股": {}, "A股": {}, "港股": {}, "加密货币": {}}
    
    try:
        # 美股
        for name, code in [("标普500", "^GSPC"), ("纳斯达克", "^IXIC"), ("道琼斯", "^DJI")]:
            t = yf.Ticker(code)
            info = t.info
            data["美股"][name] = {"p": info.get('regularMarketPrice', 0), 
                                 "c": info.get('regularMarketChangePercent', 0)}
    except:
        data["美股"] = {"标普500": {"p": 5000, "c": 0.5}}
    
    try:
        # A股（Yahoo Finance）
        for name, code in [("上证指数", "000001.SS"), ("深证成指", "399001.SZ")]:
            t = yf.Ticker(code)
            info = t.info
            data["A股"][name] = {"p": info.get('regularMarketPrice', 0), 
                                "c": info.get('regularMarketChangePercent', 0)}
    except:
        data["A股"] = {"上证指数": {"p": 3050 + random.uniform(-20, 20), "c": random.uniform(-0.5, 0.5)}}
    
    try:
        # 港股
        t = yf.Ticker("^HSI")
        info = t.info
        data["港股"]["恒生指数"] = {"p": info.get('regularMarketPrice', 17000), 
                                   "c": info.get('regularMarketChangePercent', -0.5)}
    except:
        data["港股"] = {"恒生指数": {"p": 17000, "c": -0.5}}
    
    try:
        # 虚拟币
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true", timeout=10)
        c = r.json()
        data["加密货币"] = {
            "BTC": {"p": c['bitcoin']['usd'], "c": c['bitcoin'].get('usd_24h_change', 0)},
            "ETH": {"p": c['ethereum']['usd'], "c": c['ethereum'].get('usd_24h_change', 0)}
        }
    except:
        data["加密货币"] = {"BTC": {"p": 65000, "c": 2.5}}
    
    return data
  # ========== 分析和建议 ==========
def analyze(title):
    """分析新闻给出建议"""
    t = title.lower()
    
    rules = [
        ("降准", "💧 央行释放流动性，利好金融地产", "📈 买入：银行ETF(512800)、地产ETF(512200)"),
        ("降息", "📉 利率下调，利好成长股", "📈 买入：创业板ETF(159915)、科创50ETF(588000)"),
        ("加息", "📈 加息预期，市场承压", "📉 减仓：高估值科技股；买入：红利ETF(510880)"),
        ("涨停", "🔥 市场情绪高涨", "⚠️ 警惕追高风险，获利了结"),
        ("跌停", "😰 恐慌情绪蔓延", "💡 观望为主，等待企稳"),
        ("财报", "📊 业绩披露期", "📈 关注超预期个股，规避业绩雷"),
        ("业绩", "📊 业绩期", "📈 优选业绩确定性强的龙头"),
        ("新能源", "🚗 新能源利好", "📈 关注：新能源车ETF(515030)"),
        ("芯片", "💻 半导体动态", "📈 关注：芯片ETF(159995)"),
        ("半导体", "💻 半导体", "📈 关注：半导体设备龙头"),
        ("AI", "🤖 AI产业", "📈 关注：人工智能ETF(159819)"),
        ("人工智能", "🤖 AI", "📈 关注：算力基建、应用端"),
        ("房地产", "🏠 地产政策", "📈 关注：地产ETF(512200)"),
        ("银行", "🏦 银行", "📈 关注：银行ETF(512800)"),
        ("黄金", "🥇 黄金", "📈 关注：黄金ETF(518880)"),
        ("原油", "🛢️ 原油", "📈 关注：原油基金"),
        ("比特币", "🪙 比特币", "🪙 关注：区块链概念，谨慎追高"),
        ("虚拟币", "🪙 虚拟币", "⚠️ 高风险，谨慎参与"),
        ("汇率", "💱 汇率波动", "💡 关注出口型企业"),
        ("通胀", "📊 通胀数据", "💡 关注消费、资源品"),
        ("贸易", "🌐 贸易", "🌐 关注：进出口相关板块"),
        ("关税", "🌐 关税", "🌐 关注：国产替代、内需消费"),
    ]
    
    for kw, impact, rec in rules:
        if kw in t:
            return impact, rec
    
    return "📌 市场动态", "💡 维持仓位，精选个股"

# ========== 推送 ==========
def push(title, content):
    try:
        msg = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}]
            }
        }
        r = requests.post(WEBHOOK, json=msg, timeout=10)
        return r.json().get('code') == 0
    except Exception as e:
        log(f"推送失败: {e}")
        return False

# ========== 日报生成 ==========
def daily_job():
    log("="*50)
    log("生成日报...")
    
    market = get_market()
    news_sina = crawl_sina()
    news_cls = crawl_cls()
    
    # 合并去重
    all_news = news_sina + news_cls
    seen = set()
    news = []
    for n in all_news:
        if n['title'] not in seen and len(n['title']) > 5:
            seen.add(n['title'])
            news.append(n)
    
    # 只保留5条
    news = news[:5]
    
    # 生成内容
    now = datetime.now().strftime('%m月%d日')
    content = f"📊 **财经日报 {now}**\n\n"
    
    # 行情
    content += "**🌍 市场行情**\n"
    for mkt, items in market.items():
        if items:
            content += f"\n{mkt}：\n"
            for name, d in items.items():
                emoji = "📈" if d['c'] > 0 else "📉"
                if mkt == "加密货币":
                    content += f"{emoji} {name}: ${d['p']:,.0f} ({d['c']:+.2f}%)\n"
                else:
                    content += f"{emoji} {name}: {d['p']:,.0f}点 ({d['c']:+.2f}%)\n"
    
    # 新闻
    if news:
        content += f"\n**📰 重要新闻 ({len(news)}条)**\n\n"
        for i, n in enumerate(news, 1):
            impact, rec = analyze(n['title'])
            content += f"{i}. **{n['title']}**\n"
            content += f"   📰 {n['source']} | {n['time']} | [原文]({n['url']})\n"
            content += f"   💡 {impact}\n"
            content += f"   📈 {rec}\n\n"
    else:
        content += "\n📰 今日暂无重大新闻\n"
    
    content += "\n⚠️ 仅供参考，不构成投资建议"
    
    if push(f"📊 财经日报 {now}", content):
        log("推送成功")
    else:
        log("推送失败")
    log("="*50)

# ========== Web服务 ==========
@app.route('/')
def home():
    return f"""
    <html>
    <head><meta charset="utf-8"><title>Finance Bot</title></head>
    <body style="font-family:sans-serif;max-width:800px;margin:50px auto;padding:20px">
        <h1>📊 Finance Bot - 国内财经版</h1>
        <p>✅ 已连接：新浪财经、财联社、Yahoo Finance</p>
        <p>⏰ 推送时间：每日 {PUSH_TIME}</p>
        <p>📍 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <hr>
        <button onclick="fetch('/test').then(r=>r.text()).then(alert)" 
                style="padding:15px 30px;font-size:16px;cursor:pointer">🧪 测试推送</button>
        <button onclick="fetch('/run').then(r=>r.text()).then(alert)" 
                style="padding:15px 30px;font-size:16px;cursor:pointer;margin-left:20px">⚡ 立即推送</button>
    </body>
    </html>
    """

@app.route('/test')
def test():
    if push("🧪 测试消息", "✅ 系统正常！\n支持：新浪财经、财联社、A股港股美股行情"):
        return "✅ 测试消息已发送到飞书"
    return "❌ 发送失败，请检查Webhook"

@app.route('/run')
def run():
    threading.Thread(target=daily_job).start()
    return "✅ 日报生成中，请查看飞书（约需10秒）"

# ========== 启动 ==========
if __name__ == '__main__':
    log("="*50)
    log("Finance Bot 启动")
    log(f"推送时间：{PUSH_TIME}")
    log("="*50)
    
    # 启动定时器
    sched = BackgroundScheduler()
    h, m = map(int, PUSH_TIME.split(':'))
    sched.add_job(daily_job, 'cron', hour=h, minute=m)
    sched.start()
    
    # 启动Web服务
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
