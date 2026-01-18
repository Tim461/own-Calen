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
    按照用户指定的列逻辑解析：
    数据: [时间, 国/区, 指标名称(标题), 重要性, 前值, 预测值, 公布值]
    大事: [时间, 国/区, 重要性, 事件(标题)]
    """
    events = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 获取每一行，保留竖线分隔符
    # 金十的布局通常是 div > div.item
    # 我们先获取所有文本行，用 | 分隔
    raw_lines = soup.get_text("|", strip=True).split("|")
    
    # 重新组织逻辑：因为 get_text("|") 会打散 DOM 结构，
    # 我们改用 find_all 遍历 DOM 节点来保证“行”的完整性
    rows = soup.find_all(['div', 'tr', 'li']) 
    
    # 状态机：0=无, 1=经济数据, 2=财经大事
    current_mode = 0 
    
    # 用于去重
    processed_hashes = set()

    print(f"  正在分析 {current_date} 的表格...")

    for row in rows:
        # 获取该行的文本列列表
        # 比如: ['20:30', '美国', '失业率', '3.7%', '3.8%', '3.8%']
        # 注意：重要性(星星)通常抓不到文本，所以列表长度可能会缩短
        cols = [x.strip() for x in row.get_text("|", strip=True).split('|') if x.strip()]
        
        if not cols: continue
        
        # 将列表转为字符串用于匹配标题和去重
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
        # 必须以时间开头 (HH:MM)
        time_col = cols[0]
        if not re.match(r'^\d{2}:\d{2}$', time_col):
            continue
            
        # 过滤表头 (包含“前值”、“预测值”等字样)
        if "前值" in full_line or "预测值" in full_line or "指标名称" in full_line:
            continue

        # 简单去重
        row_hash = hash(full_line)
        if row_hash in processed_hashes: continue
        processed_hashes.add(row_hash)

        # --- 3. 解析逻辑 (核心) ---
        
        evt = Event()
        
        # 设定时间
        hm = time_col.split(':')
        start_dt = datetime(
            current_date.year, current_date.month, current_date.day,
            int(hm[0]), int(hm[1]), tzinfo=pytz.timezone('Asia/Shanghai')
        )
        evt.begin = start_dt
        
        # 提取国家 (通常是第2列)
        country = cols[1] if len(cols) > 1 else ""

        # === 模式 1: 经济数据 (目标: 提取第3列作为标题) ===
        if current_mode == 1:
            # 理想结构: [时间, 国家, 指标名称, (重要性), 前值, 预测, 公布]
            # 实际抓取: [时间, 国家, 指标名称, 前值, 预测, 公布] (星星可能丢失)
            
            # 我们假设最后3个是数值 (前值, 预测, 公布)
            # 但有时数值还没出，是 "--"
            # 策略: 指标名称 = 去掉头(时间,国家) 和 去掉尾(数值) 剩下的部分
            
            # 提取数值部分 (从后往前找，直到找到不像数值的东西)
            values = []
            name_parts = []
            
            # 从第3项开始分析直到末尾
            potential_data = cols[2:] 
            
            # 简单算法：倒数3项如果包含数字、%或--，则认为是数值
            # 剩下的中间部分全是 指标名称
            
            data_vals = [] # 存放提取出的数值
            indicator_name = "未知指标"
            
            # 尝试倒序切分
            # 通常数值列最多3个 (前值, 预测, 公布)
            temp_cols = cols.copy()
            
            actual = "--"
            forecast = "--"
            previous = "--"
            
            # 如果列表够长，我们认为最后几个是数值
            # 比如 len=6: Time, Country, Name, Prev, Fore, Act
            if len(temp_cols) >= 5:
                actual = temp_cols.pop() if re.search(r'\d|--|%|K|M|B', temp_cols[-1]) else "--"
                if len(temp_cols) > 3 and re.search(r'\d|--|%|K|M|B', temp_cols[-1]):
                    forecast = temp_cols.pop()
                if len(temp_cols) > 2 and re.search(r'\d|--|%|K|M|B', temp_cols[-1]):
                    previous = temp_cols.pop()
            
            # 剩下的就是 [Time, Country, Name...]
            # pop(0) 是 Time, pop(0) 是 Country
            # 剩下的 join 起来就是 Name
            if len(temp_cols) >= 3:
                indicator_name = "".join(temp_cols[2:])
            elif len(temp_cols) > 2:
                indicator_name = temp_cols[2]
            else:
                # 容错
                indicator_name = "数据发布"

            # 设置标题 (用户要求: 指标名称作为标题)
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

        # === 模式 2: 财经大事 (目标: 提取第4列作为标题) ===
        elif current_mode == 2:
            # 理想结构: [时间, 国家, 重要性, 事件]
            # 实际抓取: [时间, 国家, 事件] (因为星星通常抓不到)
            
            # 策略: 最后一列通常就是事件内容
            event_content = cols[-1]
            
            # 稍微清洗一下，如果事件内容包含“重要性”字样则忽略
            if "重要性" in event_content: continue

            # 设置标题 (用户要求: 事件作为标题)
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
