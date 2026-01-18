import time
import re
import os
import traceback
from datetime import datetime, timedelta
import pytz
from ics import Calendar, Event

# Selenium 相关
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def get_driver():
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

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
    events = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 获取页面所有 div 和 tr 元素
    rows = soup.find_all(['div', 'tr', 'li']) 
    
    # 状态机：0=无, 1=经济数据, 2=财经大事
    current_mode = 0 
    
    # 唯一性检查集合 (防止重复添加同一条数据)
    # 格式: "HH:MM|标题"
    unique_events = set()

    print(f"  正在分析 {current_date} 的表格...")

    for row in rows:
        # 获取分割后的文本列
        text_content = row.get_text("|", strip=True)
        cols = [x.strip() for x in text_content.split('|') if x.strip()]
        
        if not cols: continue
        full_line = "".join(cols)
        
        # --- 1. 识别板块切换 ---
        if "经济数据一览" in full_line and len(cols) < 5:
            current_mode = 1
            continue
        elif "财经大事一览" in full_line and len(cols) < 5:
            current_mode = 2
            continue
        elif any(k in full_line for k in ["期货日历", "休市日历", "央行动态", "ETF"]):
            current_mode = 0
            continue
            
        if current_mode == 0: continue

        # --- 2. 关键修复：过滤大容器 (Ghost Data 杀手) ---
        # 如果一行文本里包含超过 2 个类似时间格式 (HH:MM) 的字符串，
        # 说明这是一个包含多条数据的“父容器”，直接跳过，只处理里面的子元素。
        time_pattern_count = len(re.findall(r'\d{2}:\d{2}', full_line))
        if time_pattern_count > 1:
            continue

        # --- 3. 基础过滤 ---
        # 必须以时间开头 (HH:MM)
        time_col = cols[0]
        if not re.match(r'^\d{2}:\d{2}$', time_col):
            continue
            
        # 过滤表头和无关行
        if any(k in full_line for k in ["前值", "预测值", "指标名称", "重要性", "加载更多", "查看更多", "APP"]):
            continue

        # --- 4. 解析逻辑 ---
        evt = Event()
        
        # 解析时间
        hm = time_col.split(':')
        start_dt = datetime(
            current_date.year, current_date.month, current_date.day,
            int(hm[0]), int(hm[1]), tzinfo=pytz.timezone('Asia/Shanghai')
        )
        evt.begin = start_dt
        
        # 提取国家 (第二列)
        country = cols[1] if len(cols) > 1 else ""

        # === 模式 1: 经济数据 ===
        if current_mode == 1:
            # 逻辑：提取中间部分作为标题，末尾部分作为数值
            temp_cols = cols.copy()
            
            # 默认值
            actual = "--"
            forecast = "--"
            previous = "--"
            
            # 尝试从末尾提取数值 (倒序提取直到遇到非数值)
            # 判定标准：包含数字、% 或者就是 --
            # 最多提取 3 个
            extracted_values = []
            for _ in range(3):
                if len(temp_cols) > 2: # 保证至少剩下 Time, Country
                    last_val = temp_cols[-1]
                    # 如果长得像数值
                    if re.search(r'\d|--|%|K|M|B', last_val) and len(last_val) < 15:
                        extracted_values.append(temp_cols.pop())
                    else:
                        break
            
            # 还原数值顺序 (因为是倒序pop出来的)
            # 网页顺序通常是: 前值 -> 预测 -> 公布
            # pop顺序: 公布 -> 预测 -> 前值
            if len(extracted_values) >= 1: actual = extracted_values[0]
            if len(extracted_values) >= 2: forecast = extracted_values[1]
            if len(extracted_values) >= 3: previous = extracted_values[2]
            
            # 剩下的 temp_cols 去掉前两项(时间、国家)，剩下的就是名称
            if len(temp_cols) >= 3:
                indicator_name = "".join(temp_cols[2:])
            elif len(temp_cols) > 2:
                indicator_name = temp_cols[2]
            else:
                continue # 数据太残缺，跳过

            # 唯一性检查
            uid = f"{time_col}|{indicator_name}"
            if uid in unique_events: continue
            unique_events.add(uid)

            # 设置日历项
            evt.name = f"📊[{country}] {indicator_name}"
            evt.description = (
                f"【经济数据】\n"
                f"指标: {indicator_name}\n"
                f"国家: {country}\n"
                f"------------------\n"
                f"前值: {previous}\n"
                f"预测: {forecast}\n"
                f"公布: {actual}"
            )
            evt.duration = timedelta(minutes=15)
            events.append(evt)
            print(f"    [数据] {indicator_name}")

        # === 模式 2: 财经大事 ===
        elif current_mode == 2:
            # 逻辑：最后一列是事件
            event_content = cols[-1]
            
            # 过滤：如果内容包含“重要性”或者是重复的国家名，可能是解析错误
            if "重要性" in event_content or event_content == country:
                continue

            # 唯一性检查
            uid = f"{time_col}|{event_content}"
            if uid in unique_events: continue
            unique_events.add(uid)

            # 这里的 📢 就是小喇叭，你可以删掉它，或者换成别的
            evt.name = f"📢[{country}] {event_content}"
            evt.description = (
                f"【财经大事】\n"
                f"国家: {country}\n"
                f"时间: {time_col}\n"
                f"事件: {event_content}"
            )
            evt.duration = timedelta(minutes=30)
            events.append(evt)
            print(f"    [大事] {event_content}")

    return events

def run_scraper():
    cal = Calendar()
    driver = get_driver()
    if not driver:
        exit(1)

    try:
        base_url = "https://qihuo.jin10.com/calendar.html#/"
        today = datetime.now(pytz.timezone('Asia/Shanghai')).date()
        
        # 抓取未来 7 天
        days_to_scrape = 7
        total_count = 0

        for i in range(days_to_scrape):
            target_date = today + timedelta(days=i)
            date_str = target_date.strftime('%Y-%m-%d')
            full_url = f"{base_url}{date_str}"
            
            print(f"\n[{i+1}/{days_to_scrape}] 解析页面: {full_url}")
            
            try:
                driver.get(full_url)
                time.sleep(5) 
                html = driver.page_source
                day_events = parse_day_content(html, target_date)
                
                for e in day_events:
                    cal.events.add(e)
                    total_count += 1
                
            except Exception as e:
                print(f"    ! 解析出错: {e}")

    except Exception as e:
        print(f"全局错误: {traceback.format_exc()}")
    finally:
        driver.quit()

    if total_count > 0:
        output_file = 'jin10_calendar.ics'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(cal.serialize())
        print(f"\n成功生成 {output_file}，包含 {total_count} 个事件。")
    else:
        print("\n未获取到数据。")

if __name__ == "__main__":
    run_scraper()
