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

def parse_time_str(time_str, current_date):
    """
    辅助函数：解析时间字符串
    返回: (start_dt, is_fuzzy)
    """
    # 移除可能的空白字符
    time_str = time_str.strip()
    
    # 情况1: 标准 HH:MM 格式 (例如 20:30)
    if re.match(r'^\d{1,2}:\d{2}$', time_str):
        hm = time_str.split(':')
        start_dt = datetime(
            current_date.year, current_date.month, current_date.day,
            int(hm[0]), int(hm[1]), tzinfo=pytz.timezone('Asia/Shanghai')
        )
        return start_dt, False
    
    # 情况2: 汉字或非标准时间 (例如 "待定", "23日", "下午")
    # 统一处理为当天的 00:00，并标记为模糊时间
    else:
        start_dt = datetime(
            current_date.year, current_date.month, current_date.day,
            0, 0, tzinfo=pytz.timezone('Asia/Shanghai')
        )
        return start_dt, True

def parse_day_content(html_content, current_date):
    events = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 使用 | 分隔符提取文本
    raw_text = soup.get_text("|", strip=True)
    
    mode = "UNKNOWN" 
    # 直接查找容器行，避免混乱
    rows = soup.find_all(['div', 'tr', 'li'])
    processed_hashes = set()

    print(f"  正在分析页面结构...")

    for row in rows:
        row_str = row.get_text("|", strip=True)
        
        # 1. 模式切换检测
        if "经济数据一览" in row_str and len(row_str) < 30:
            mode = "DATA"
            print("    -> 切换到 [经济数据] 模式")
            continue
        elif "财经大事一览" in row_str and len(row_str) < 30:
            mode = "EVENT"
            print("    -> 切换到 [财经大事] 模式")
            continue
        elif "期货日历" in row_str or "休市日历" in row_str:
            mode = "UNKNOWN"
            continue
            
        if mode == "UNKNOWN":
            continue

        # 2. 数据行拆分
        cols = [c.strip() for c in row_str.split('|') if c.strip()]
        if not cols: continue

        # 3. 过滤表头和干扰行
        if any(h in row_str for h in ["前值", "预测值", "公布值", "详情", "今值", "重要性"]):
            continue
        
        # 简单去重
        row_hash = hash(row_str)
        if row_hash in processed_hashes:
            continue
        processed_hashes.add(row_hash)

        # --- 处理 [经济数据] ---
        # 你的逻辑：时间 | (图标-无文本) | 指标名称 | ...
        # 实际 cols: [时间, 指标名称, ..., 数值]
        if mode == "DATA":
            if len(cols) < 2: continue 

            time_str = cols[0]
            # 如果第一列太长，通常不是时间而是标题行
            if len(time_str) > 10: continue

            # 指标名称直接取第2列
            name = cols[1] 
            
            # 提取数值：取最后3列作为候选
            potential_values = cols[-3:] 
            prev, forecast, actual = "--", "--", "--"
            
            # 只有当总列数足够时才尝试解析数值
            if len(cols) >= 4:
                if len(potential_values) == 3:
                    prev, forecast, actual = potential_values
                elif len(potential_values) == 2:
                    prev, forecast = potential_values
            
            # 简单清洗非数值内容
            def is_valid_val(s): return len(s) < 20 and (any(c.isdigit() for c in s) or '--' in s or '%' in s)
            if not is_valid_val(prev): prev = "--"
            if not is_valid_val(actual): actual = "--"

            evt = Event()
            start_dt, is_fuzzy = parse_time_str(time_str, current_date)
            
            prefix = f"[{time_str}]" if is_fuzzy else ""
            evt.name = f"📊{prefix} {name}"
            evt.begin = start_dt
            evt.duration = timedelta(minutes=15)
            
            evt.description = (
                f"【经济数据】\n"
                f"时间: {time_str}\n"
                f"指标: {name}\n"
                f"------------------\n"
                f"前值: {prev}\n"
                f"预测: {forecast}\n"
                f"公布: {actual}\n"
            )
            events.append(evt)
            print(f"    [数据] {time_str} | {name} | 公布:{actual}")

        # --- 处理 [财经大事] ---
        # 你的逻辑：时间 | 国/区(汉字) | ... | 事件
        # 实际 cols: [时间, 国家, 事件...]
        elif mode == "EVENT":
            if len(cols) < 3: continue

            time_str = cols[0]
            if len(time_str) > 10: continue

            country = cols[1]
            # 剩下的合并为内容
            content = " ".join(cols[2:]) 

            evt = Event()
            start_dt, is_fuzzy = parse_time_str(time_str, current_date)

            prefix = f"[{time_str}]" if is_fuzzy else ""
            # 标题过长则截断
            title_text = content[:20] + "..." if len(content) > 20 else content
            evt.name = f"📢{prefix}[{country}] {title_text}"
            
            evt.begin = start_dt
            evt.duration = timedelta(minutes=30)
            
            evt.description = (
                f"【财经大事】\n"
                f"时间: {time_str}\n"
                f"地区: {country}\n"
                f"事件: {content}\n"
            )
            events.append(evt)
            print(f"    [大事] {time_str} | {country} | {title_text}")

    return events

def run_scraper():
    cal = Calendar()
    driver = get_driver()
    if not driver:
        exit(1)

    try:
        base_url = "https://qihuo.jin10.com/calendar.html#/"
        today = datetime.now(pytz.timezone('Asia/Shanghai')).date()
        
        # 抓取今天 + 未来 7 天
        days_to_scrape = 8 
        total_count = 0

        for i in range(days_to_scrape):
            target_date = today + timedelta(days=i)
            date_str = target_date.strftime('%Y-%m-%d')
            full_url = f"{base_url}{date_str}"
            
            print(f"\n[{i+1}/{days_to_scrape}] 抓取: {full_url}")
            
            try:
                driver.get(full_url)
                time.sleep(6) # 等待页面动态加载
                
                html = driver.page_source
                day_events = parse_day_content(html, target_date)
                
                for e in day_events:
                    cal.events.add(e)
                    total_count += 1
                
                if not day_events:
                    print("    (无数据或抓取被拦截)")

            except Exception as e:
                print(f"    ! 页面出错: {e}")

    except Exception as e:
        print(f"全局错误: {traceback.format_exc()}")
    finally:
        driver.quit()

    # 保存文件
    if total_count > 0:
        output_file = 'jin10_calendar.ics'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(cal.serialize())
