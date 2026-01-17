import time
import re
import os
import traceback
from datetime import datetime
import pytz
from ics import Calendar, Event

# 引入 Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def get_html_via_selenium(url):
    print(f"正在启动浏览器访问: {url}")
    
    options = Options()
    # 核心修复：添加适应服务器环境的参数
    options.add_argument("--headless") # 无头模式
    options.add_argument("--no-sandbox") # 绕过沙盒限制
    options.add_argument("--disable-dev-shm-usage") # 解决内存不足问题
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222") # 解决DevTools报错
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 如果环境变量中有 Chrome 路径（由 GitHub Action 注入），则使用它
    chrome_binary_path = os.environ.get("CHROME_PATH")
    if chrome_binary_path:
        print(f"使用指定的 Chrome 路径: {chrome_binary_path}")
        options.binary_location = chrome_binary_path

    driver = None
    try:
        # 使用 webdriver_manager 自动匹配驱动
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        driver.get(url)
        print("网页已打开，等待数据加载 (15秒)...")
        time.sleep(15) # 适当延长等待时间
        
        page_source = driver.page_source
        return page_source

    except Exception as e:
        print("!!! 浏览器启动或执行失败 !!!")
        print(traceback.format_exc()) # 打印完整的错误详情
        return None
        
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

def parse_and_generate_ics(html_content):
    if not html_content:
        print("错误: 网页内容为空，无法生成日历")
        # 抛出异常以触发 Action 失败，引起注意
        exit(1)

    soup = BeautifulSoup(html_content, 'html.parser')
    cal = Calendar()
    count = 0
    
    # 获取今天日期
    today_date = datetime.now(pytz.timezone('Asia/Shanghai')).date()
    current_date_obj = today_date
    
    # 提取所有文本行
    text_lines = soup.get_text("\n", strip=True).split("\n")
    
    # 关键词过滤
    target_exchanges = ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'LME', 'COMEX', 'NYMEX', 'INE', '中金所', '上期所', '大商所', '郑商所']
    event_keywords = ['最后交易日', '首个通知日', '到期日', '休市']

    print(f"开始解析网页文本，共 {len(text_lines)} 行...")

    for line in text_lines:
        line = line.strip()
        
        # 1. 尝试识别日期行 (格式如: 2023年10月27日 星期五)
        if "年" in line and "月" in line and "日" in line:
            try:
                date_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', line)
                if date_match:
                    current_date_obj = datetime(
                        int(date_match.group(1)),
                        int(date_match.group(2)),
                        int(date_match.group(3))
                    ).date()
                    continue
            except:
                pass

        # 2. 识别事件
        # 条件：包含交易所名称 OR 包含特定事件关键词
        is_exchange = any(k in line.upper() for k in target_exchanges)
        is_event_type = any(k in line for k in event_keywords)
        
        if (is_exchange or is_event_type) and len(line) > 4:
            # 排除纯数字或太短的干扰项
            if re.match(r'^\d+$', line):
                continue
                
            evt = Event()
            evt.name = line
            evt.begin = current_date_obj
            evt.make_all_day()
            evt.description = f"来源: 金十期货\n原文: {line}"
            
            cal.events.add(evt)
            count += 1

    if count > 0:
        with open('futures.ics', 'w', encoding='utf-8') as f:
            f.writelines(cal.serialize())
        print(f"成功: 已生成 futures.ics，包含 {count} 个事件")
    else:
        print("警告: 脚本运行成功，但没有抓取到任何事件。")
        print("可能原因: 1. 今日无重要事件 2. 网页结构变更 3. 浏览器被反爬")
        # 打印部分网页内容帮助调试
        print("调试 - 网页前500字符:", html_content[:500])

if __name__ == "__main__":
    try:
        url = "https://qihuo.jin10.com/calendar.html#/"
        html = get_html_via_selenium(url)
        parse_and_generate_ics(html)
    except Exception as e:
        print("程序发生未捕获异常:")
        print(traceback.format_exc())
        exit(1)
