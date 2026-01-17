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
    # 模拟真实浏览器 User-Agent，防止被识别为爬虫
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
    time_str = time_str.strip()
    if re.match(r'^\d{1,2}:\d{2}$', time_str):
        hm = time_str.split(':')
        start_dt = datetime(
            current_date.year, current_date.month, current_date.day,
            int(hm[0]), int(hm[1]), tzinfo=pytz.timezone('Asia/Shanghai')
        )
        return start_dt, False
    else:
        start_dt = datetime(
            current_date.year, current_date.month, current_date.day,
            0, 0, tzinfo=pytz.timezone('Asia/Shanghai')
        )
        return start_dt, True

def parse_day_content(html_content, current_date):
    events = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 【调试】打印一下页面标题，确认页面加载成功
    print(f"  页面标题: {soup.title.string if soup.title else '无标题'}")
    
    # 稍微放宽匹配条件，去掉 "|", 让文本更连贯
    raw_text_check = soup.get_text()
    if "经济数据" not in raw_text_check and "财经大事" not in raw_text_check:
        print("  [警告] 页面中未发现'经济数据'或'财经大事'关键词，可能是反爬虫拦截或加载未完成。")

    mode = "UNKNOWN" 
    rows = soup.find_all(['div', 'tr', 'li'])
    processed_hashes = set()

    for i, row in enumerate(rows):
        row_str = row.get_text("|", strip=True)
        
        # 【调试】打印前几行看看结构（仅打印前10行，避免日志爆炸）
        if i < 10: 
            print(f"  [Row-{i}] {row_str[:50]}...")

        # 1. 模式切换检测 (放宽匹配逻辑)
        # 有时候 "经济数据一览" 可能会被标签隔开
        clean_row_str = row_str.replace("|", "").replace(" ", "")
        
        if "经济数据" in clean_row_str and len(clean_row_str) < 30:
            mode = "DATA"
            print("    -> 切换到 [经济数据] 模式")
            continue
        elif "财经大事" in clean_row_str and len(clean_row_str) < 30:
            mode = "EVENT"
            print("    -> 切换到 [财经大事] 模式")
            continue
        elif "期货日历" in clean_row_str or "休市日历" in clean_row_str:
            mode = "UNKNOWN"
            continue
            
        if mode == "UNKNOWN":
            continue

        cols = [c.strip() for c in row_str.split('|') if c.strip()]
        if not cols: continue

        # 过滤表头
        if any(h in row_str for h in ["前值", "预测值", "公布值", "详情", "今值", "重要性"]):
            continue
        
        row_hash = hash(row_str)
        if row_hash in processed_hashes: continue
        processed_hashes.add(row_hash)

        # --- DATA ---
        if mode == "DATA":
            if len(cols) < 2: continue 
            time_str = cols[0]
            if len(time_str) > 10: continue # 过滤杂项

            name = cols[1] 
            potential_values = cols[-3:] 
            prev, forecast, actual = "--", "--", "--"
            
            if len(cols) >= 4:
                if len(potential_values) == 3:
                    prev, forecast, actual = potential_values
                elif len(potential_values) == 2:
                    prev, forecast = potential_values
            
            def is_valid_val(s): return len(s) < 20 and (any(c.isdigit() for c in s) or '--' in s or '%' in s)
            if not is_valid_val(prev): prev = "--"
            if not is_valid_val(actual): actual = "--"

            evt = Event()
            start_dt, is_fuzzy = parse_time_str(time_str, current_date)
            prefix = f"[{time_str}]" if is_fuzzy else ""
            evt.name = f"📊{prefix} {name}"
            evt.begin = start_dt
            evt.duration = timedelta(minutes=15)
            evt.description = f"【经济数据】\n时间: {time_str}\n指标: {name}\n公布: {actual}\n预测: {forecast}\n前值: {prev}"
            events.append(evt)
            print(f"    [数据] {time_str} | {name} | 公布:{actual}")

        # --- EVENT ---
        elif mode == "EVENT":
            if len(cols) < 3: continue
            time_str = cols[0]
            if len(time_str) > 10: continue

            country = cols[1]
            content = " ".join(cols[2:]) 

            evt = Event()
            start_dt, is_fuzzy = parse_time_str(time_str, current_date)
            prefix = f"[{time_str}]" if is_fuzzy else ""
            title_text = content[:20] + "..." if len(content) > 20 else content
            evt.name = f"📢{prefix}[{country}] {title_text}"
            evt.begin = start_dt
            evt.duration = timedelta(minutes=30)
            evt.description = f"【财经大事】\n时间: {time_str}\n地区: {country}\n事件: {content}"
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
        
        # 只抓今天一天，先测试能不能跑通
        days_to_scrape = 1 
        total_count = 0

        for i in range(days_to_scrape):
            target_date = today + timedelta(days=i)
            date_str = target_date.strftime('%Y-%m-%d')
            full_url = f"{base_url}{date_str}"
            
            print(f"\n[{i+1}/{days_to_scrape}] 抓取: {full_url}")
            
            try:
                driver.get(full_url)
                # 增加等待时间，防止加载过慢
                time.sleep(10) 
                
                html = driver.page_source
                day_events = parse_day_content(html, target_date)
                
                for e in day_events:
                    cal.events.add(e)
                    total_count += 1
                
                if not day_events:
                    print("    (该页面未提取到事件)")

            except Exception as e:
                print(f"    ! 页面出错: {e}")

    except Exception as e:
        print(f"全局错误: {traceback.format_exc()}")
    finally:
        driver.quit()

    # 【强制保存】：哪怕 total_count 为 0 也保存文件，
    # 这样可以验证是否是 Git 提交的问题，还是真的没数据
    output_file = 'jin10_calendar.ics'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(cal.serialize())
    
    if total_count > 0:
        print(f"\n生成成功: {output_file} (包含 {total_count} 条数据)")
    else:
        print(f"\n警告: 未抓取到任何数据，但已强制生成空文件: {output_file}")

if __name__ == "__main__":
    run_scraper()
