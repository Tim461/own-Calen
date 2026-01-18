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
    """
    逻辑：
    1. 时间列可能是 "21:30" 也可能是 "待定/上午" 等汉字。
    2. 经济数据标题 = 指标名称；时间
    3. 财经大事标题 = 事件；时间
    """
    events = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 遍历所有行节点
    rows = soup.find_all(['div', 'tr', 'li']) 
    
    # 状态机：0=无, 1=经济数据, 2=财经大事
    current_mode = 0 
    processed_hashes = set()

    print(f"  正在分析 {current_date} ...")

    for row in rows:
        # 提取文本列
        cols = [x.strip() for x in row.get_text("|", strip=True).split('|') if x.strip()]
        if not cols: continue
        
        full_line = "".join(cols)
        
        # --- 1. 切换模式 ---
        if "经济数据一览" in full_line and len(cols) < 5:
            current_mode = 1
            continue
        elif "财经大事一览" in full_line and len(cols) < 5:
            current_mode = 2
            continue
        elif "期货日历" in full_line or "休市日历" in full_line:
            current_mode = 0
            continue
            
        if current_mode == 0: continue

        # --- 2. 基础过滤 ---
        # 第一列是时间。如果是表头（"时间"），跳过
        time_str = cols[0]
        if "时间" in time_str or "前值" in full_line or "指标名称" in full_line:
            continue
            
        # 排除纯日期的行 (例如 "2026-01-18" 或 "星期日")
        if re.search(r'^\d{4}-\d{2}-\d{2}', time_str) or "星期" in time_str:
            continue

        # 去重
        row_hash = hash(full_line)
        if row_hash in processed_hashes: continue
        processed_hashes.add(row_hash)

        # --- 3. 构建事件对象 ---
        evt = Event()
        
        # 处理日历的时间设定 (begin)
        # 尝试从 time_str 中提取 HH:MM
        # 如果提取不到（比如是 "待定"），则设为全天事件
        time_match = re.search(r'(\d{1,2}):(\d{2})', time_str)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            start_dt = datetime(
                current_date.year, current_date.month, current_date.day,
                hour, minute, tzinfo=pytz.timezone('Asia/Shanghai')
            )
            evt.begin = start_dt
            evt.duration = timedelta(minutes=15)
        else:
            # 是汉字时间 (待定, 上午等) -> 全天事件
            evt.begin = current_date
            evt.make_all_day()

        # 提取国家 (通常第2列)
        country = cols[1] if len(cols) > 1 else ""

        # === 模式 1: 经济数据 ===
        if current_mode == 1:
            # 提取数值 (前值/预测/公布) 从尾部找
            temp_cols = cols.copy()
            
            actual = "--"
            forecast = "--"
            previous = "--"
            
            # 尝试弹出尾部的数值
            # 条件：包含数字, %, --, K, M, B
            if len(temp_cols) >= 5: # 确保有足够列才去弹
                if re.search(r'\d|--|%|K|M|B', temp_cols[-1]): actual = temp_cols.pop()
                if re.search(r'\d|--|%|K|M|B', temp_cols[-1]): forecast = temp_cols.pop()
                if re.search(r'\d|--|%|K|M|B', temp_cols[-1]): previous = temp_cols.pop()

            # 剩下的部分：去掉头两列(时间, 国家)，中间就是名称
            # 现在的 temp_cols = [时间, 国家, 指标名称...]
            if len(temp_cols) > 2:
                indicator_name = "".join(temp_cols[2:])
            else:
                indicator_name = "数据发布"

            # 【用户需求】标题格式：指标名称；时间
            evt.name = f"{indicator_name}；{time_str}"
            
            evt.description = (
                f"国家: {country}\n"
                f"前值: {previous}\n"
                f"预测: {forecast}\n"
                f"公布: {actual}\n"
                f"原始时间: {time_str}"
            )
            events.append(evt)
            print(f"    [数据] {evt.name}")

        # === 模式 2: 财经大事 ===
        elif current_mode == 2:
            # 最后一列通常是事件
            event_content = cols[-1]
            if "重要性" in event_content: continue

            # 【用户需求】标题格式：事件；时间
            evt.name = f"{event_content}；{time_str}"
            
            evt.description = (
                f"国家: {country}\n"
                f"原始时间: {time_str}\n"
                f"事件详情: {event_content}"
            )
            events.append(evt)
            print(f"    [大事] {evt.name}")

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
            
            print(f"\n[{i+1}/{days_to_scrape}] 处理页面: {full_url}")
            
            try:
                driver.get(full_url)
                time.sleep(5) 
                
                html = driver.page_source
                day_events = parse_day_content(html, target_date)
                
                for e in day_events:
                    cal.events.add(e)
                    total_count += 1
                
            except Exception as e:
                print(f"    ! 出错: {e}")

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
