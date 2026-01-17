import time
import re
import os
import traceback
from datetime import datetime, timedelta
import pytz
from ics import Calendar, Event

# Selenium 相关库
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def get_driver():
    """初始化并返回一个配置好的 Chrome Driver"""
    options = Options()
    # GitHub Actions 必须的参数
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 获取 GitHub Action 提供的 Chrome 路径
    chrome_binary_path = os.environ.get("CHROME_PATH")
    if chrome_binary_path:
        options.binary_location = chrome_binary_path

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        print(f"浏览器初始化失败: {e}")
        return None

def parse_day_content(html_content, current_date):
    """解析单日页面的 HTML，返回事件列表"""
    events = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 获取页面所有文本
    text_lines = soup.get_text("\n", strip=True).split("\n")
    
    # 关键词库：包含常见交易所和事件类型
    # 中文: 上期所, 大商所, 郑商所, 中金所, 广期所
    # 英文: CFFEX, SHFE, DCE, CZCE, GFEX, INE, LME, COMEX, NYMEX, CBOT, ICE, SGX
    keywords = [
        'CFFEX', 'SHFE', 'DCE', 'CZCE', 'GFEX', 'INE', 'LME', 'COMEX', 'NYMEX', 'CBOT', 'ICE', 'SGX',
        '中金所', '上期所', '大商所', '郑商所', '广期所', '能源中心',
        '最后交易日', '首个通知日', '最后通知日', '到期日', '休市'
    ]

    for line in text_lines:
        line = line.strip()
        if len(line) < 4: continue # 忽略太短的字符
        
        # 排除纯数字或纯日期的行
        if re.match(r'^[\d\-\:\s年月日星期]+$', line):
            continue

        # 检查是否包含关键词
        if any(kw in line.upper() for kw in keywords):
            evt = Event()
            evt.name = line
            evt.begin = current_date
            evt.make_all_day()
            evt.description = f"日期: {current_date}\n来源: 金十期货\n原文: {line}"
            events.append(evt)
            print(f"  [√] 抓取到: {line}")
            
    return events

def run_scraper():
    cal = Calendar()
    driver = get_driver()
    if not driver:
        exit(1)

    try:
        # 设定抓取范围：今天 + 未来 7 天
        base_url = "https://qihuo.jin10.com/calendar.html#/"
        today = datetime.now(pytz.timezone('Asia/Shanghai')).date()
        
        total_events = 0

        for i in range(8): # 抓取 8 天
            target_date = today + timedelta(days=i)
            date_str = target_date.strftime('%Y-%m-%d')
            full_url = f"{base_url}{date_str}"
            
            print(f"\n--- 正在处理: {date_str} [{full_url}] ---")
            
            try:
                driver.get(full_url)
                # 强制等待，让 Vue.js 渲染数据
                # 如果是第一页等待久一点，后续可以稍短，但为了稳定统一设为 8 秒
                time.sleep(8) 
                
                html = driver.page_source
                day_events = parse_day_content(html, target_date)
                
                for e in day_events:
                    cal.events.add(e)
                    total_events += 1
                    
                if not day_events:
                    print(f"  [-] 该日无符合条件的事件 (可能是周末或无数据)")
                    
            except Exception as e:
                print(f"  [!] 处理 {date_str} 时出错: {e}")

    except Exception as e:
        print(f"致命错误: {traceback.format_exc()}")
    finally:
        driver.quit()

    # 保存结果
    if total_events > 0:
        output_file = 'futures.ics'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(cal.serialize())
        print(f"\n成功生成 {output_file}，共 {total_events} 个事件。")
    else:
        print("\n未抓取到任何事件。")
        # 即使没有事件，为了防止 Action 报错，我们可以不生成文件或生成空文件，这里选择不生成

if __name__ == "__main__":
    run_scraper()
