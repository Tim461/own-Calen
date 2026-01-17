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
    精准解析：利用 | 分隔符还原表格结构，提取经济数据和财经大事
    """
    events = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 核心技巧：使用 | 作为分隔符提取文本，这样能保留表格的列结构
    # 例如： "20:30|美国|CPI年率|3.4%|3.2%|--"
    raw_text = soup.get_text("|", strip=True)
    lines = raw_text.split("|")
    
    # 重组逻辑：因为 split('|') 会把所有单元格打散成一个巨大的列表
    # 我们需要根据上下文来“拼凑”出每一行
    
    # 状态机模式
    mode = "UNKNOWN" # UNKNOWN, DATA (经济数据), EVENT (财经大事)
    
    # 临时缓冲区，用于存储正在拼凑的一行数据
    buffer_row = []
    
    print(f"  正在分析页面结构...")

    # 为了更精准，我们直接查找包含特定关键词的容器行
    # 金十的每一行通常是一个 div 或者 tr
    rows = soup.find_all(['div', 'tr', 'li'])
    
    processed_hashes = set() # 用于去重

    for row in rows:
        row_str = row.get_text("|", strip=True)
        
        # 1. 模式切换检测
        if "经济数据一览" in row_str and len(row_str) < 20:
            mode = "DATA"
            print("    -> 切换到 [经济数据] 模式")
            continue
        elif "财经大事一览" in row_str and len(row_str) < 20:
            mode = "EVENT"
            print("    -> 切换到 [财经大事] 模式")
            continue
        elif "期货日历" in row_str or "休市日历" in row_str:
            mode = "UNKNOWN"
            continue
            
        if mode == "UNKNOWN":
            continue

        # 2. 数据行识别
        # 将行文本拆分为列
        cols = [c.strip() for c in row_str.split('|') if c.strip()]
        
        if not cols: continue

        # 特征识别：第一列必须是时间 (HH:MM)
        # 且该行不能包含表头关键词 "前值", "预测值", "重要性"
        if not re.match(r'^\d{2}:\d{2}$', cols[0]):
            continue
        if any(h in row_str for h in ["前值", "预测值", "公布值", "事件", "地区"]):
            continue

        # 简单去重：因为DOM结构嵌套，同一行数据可能被父级div和子级div分别读取一次
        row_hash = hash(row_str)
        if row_hash in processed_hashes:
            continue
        processed_hashes.add(row_hash)

        # --- 处理 [经济数据] ---
        if mode == "DATA":
            # 理想列结构: 时间 | 地区 | 指标名 | (星星/重要性) | 前值 | 预测值 | 公布值
            # 实际抓取可能有所波动，我们根据长度和内容来映射
            
            time_str = cols[0]
            country = cols[1] if len(cols) > 1 else "全球"
            name = cols[2] if len(cols) > 2 else "未知指标"
            
            # 提取数值：从后往前找，通常最后三列是 [前值, 预测, 公布] 的各种组合
            # 金十通常顺序：前值 | 预测 | 公布
            # 或者是：公布 | 预测 | 前值 (取决于抓取顺序，通常 bs4 是按阅读顺序)
            
            # 策略：取列表最后3个元素作为数值候选
            potential_values = cols[-3:] 
            
            # 初始化
            prev, forecast, actual = "--", "--", "--"
            
            # 只有当列数足够多时才尝试解析数值
            if len(cols) >= 5:
                # 假设标准情况: Time, Country, Name, ..., Prev, Forecast, Actual
                if len(potential_values) == 3:
                    prev = potential_values[0]
                    forecast = potential_values[1]
                    actual = potential_values[2]
                elif len(potential_values) == 2:
                    prev = potential_values[0]
                    forecast = potential_values[1]
            
            # 过滤掉非数值的干扰项（比如把指标名当成了前值）
            # 简单的启发式过滤: 数值列通常比较短，且包含数字或 % 或 --
            def is_value(s): return len(s) < 15 and (re.search(r'\d', s) or '--' in s)
            
            if not is_value(prev): prev = "--"
            if not is_value(forecast): forecast = "--"
            if not is_value(actual): actual = "--"

            # 创建日历事件
            evt = Event()
            evt.name = f"📊[{country}] {name}"
            
            hm = time_str.split(':')
            start_dt = datetime(
                current_date.year, current_date.month, current_date.day,
                int(hm[0]), int(hm[1]), tzinfo=pytz.timezone('Asia/Shanghai')
            )
            evt.begin = start_dt
            evt.duration = timedelta(minutes=15)
            
            evt.description = (
                f"【经济数据】\n"
                f"国家: {country}\n"
                f"指标: {name}\n"
                f"------------------\n"
                f"前值: {prev}\n"
                f"预测: {forecast}\n"
                f"公布: {actual}\n"
            )
            events.append(evt)
            print(f"    [数据] {time_str} {name} (前:{prev} 预:{forecast} 公:{actual})")

        # --- 处理 [财经大事] ---
        elif mode == "EVENT":
            # 理想列结构: 时间 | 地区 | 城市/重要性 | 事件内容
            time_str = cols[0]
            country = cols[1] if len(cols) > 1 else ""
            
            # 合并剩余列作为事件详情
            content = " ".join(cols[2:])
            
            evt = Event()
            # 标题截取前20字
            title_text = content[:20] + "..." if len(content) > 20 else content
            evt.name = f"📢[{country}] {title_text}"
            
            hm = time_str.split(':')
            start_dt = datetime(
                current_date.year, current_date.month, current_date.day,
                int(hm[0]), int(hm[1]), tzinfo=pytz.timezone('Asia/Shanghai')
            )
            evt.begin = start_dt
            evt.duration = timedelta(minutes=30)
            
            evt.description = (
                f"【财经大事】\n"
                f"国家: {country}\n"
                f"时间: {time_str}\n"
                f"事件详情: {content}\n"
            )
            events.append(evt)
            print(f"    [大事] {time_str} {title_text}")

    return events

def run_scraper():
    cal = Calendar()
    driver = get_driver()
    if not driver:
        exit(1)

    try:
        base_url = "https://qihuo.jin10.com/calendar.html#/"
        today = datetime.now(pytz.timezone('Asia/Shanghai')).date()
        
        # 抓取范围：今天 + 未来 7 天
        # 如果你想测试那4个特定日期，可以在这里手动修改 target_date
        days_to_scrape = 8 
        total_count = 0

        for i in range(days_to_scrape):
            target_date = today + timedelta(days=i)
            date_str = target_date.strftime('%Y-%m-%d')
            full_url = f"{base_url}{date_str}"
            
            print(f"\n[{i+1}/{days_to_scrape}] 抓取: {full_url}")
            
            try:
                driver.get(full_url)
                # 页面加载等待 6 秒
                time.sleep(6) 
                
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

    # 保存
    if total_count > 0:
        output_file = 'jin10_calendar.ics'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(cal.serialize())
        print(f"\n生成成功: {output_file} (包含 {total_count} 条数据)")
    else:
        print("\n未抓取到任何数据。")

if __name__ == "__main__":
    run_scraper()
