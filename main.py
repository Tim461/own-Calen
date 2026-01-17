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

def clean_text_list(text_str):
    """辅助函数：将 'aaa|bbb||ccc' 清洗为 ['aaa', 'bbb', 'ccc']"""
    if not text_str:
        return []
    # 分割并去除空白项
    return [x.strip() for x in text_str.split('|') if x.strip()]

def parse_day_content(html_content, current_date):
    """
    结构化解析：提取表格形式的经济数据和财经大事
    """
    events = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 查找所有的大板块容器
    # 金十的结构通常是 headers 跟着 content
    # 我们使用 get_text('|') 来保留列结构
    raw_lines = soup.get_text("|", strip=True).split("|")
    
    # 重组 line：因为 get_text('|') 会把一行拆得很碎，我们需要根据视觉上的“行”来重组
    # 但金十的布局比较复杂，这里采用基于“板块定位”+“行扫描”的策略
    
    # 重新获取 HTML 块进行精细处理
    # 寻找包含“经济数据一览”的父级容器
    # 金十页面通常有明确的 class，但混淆严重。我们遍历所有 div 行。
    
    # --- 策略更新：针对行的遍历 ---
    # 我们把 HTML 里的每一行 (div/tr) 拿出来单独处理
    rows = soup.find_all(['div', 'tr']) 
    
    current_section = None # 'DATA' or 'EVENT'
    
    processed_texts = set() # 防止重复添加包含关系的 div

    print(f"  正在分析 {current_date} ...")

    for row in rows:
        # 获取该行的文本列表 (保留列分隔)
        row_text_str = row.get_text("|", strip=True)
        # 如果这行文本已经被包含在更大的父级里处理过，跳过 (简单的去重)
        # (实际操作中，完全去重较难，我们通过特征识别来过滤)
        
        cols = clean_text_list(row_text_str)
        if not cols: continue
        
        full_line_text = "".join(cols)

        # 1. 识别板块头
        if "经济数据一览" in full_line_text and len(cols) < 5:
            current_section = 'DATA'
            continue
        if "财经大事一览" in full_line_text and len(cols) < 5:
            current_section = 'EVENT'
            continue
        if "期货日历" in full_line_text or "休市日历" in full_line_text:
            current_section = None
            continue

        if current_section is None:
            continue

        # 2. 识别数据行
        # 特征：第一列通常是时间 HH:MM
        time_col = cols[0]
        if not re.match(r'^\d{2}:\d{2}$', time_col):
            continue
        
        # 再次检查：防止抓取到表头（时间、前值、预测值...）
        if "前值" in full_line_text or "预测值" in full_line_text:
            continue
            
        # 防止重复：金十的 DOM 结构嵌套很深，一个 row 可能被 find_all 找到多次
        # 我们用整行的 hash 来简单去重
        row_hash = hash(full_line_text)
        if row_hash in processed_texts:
            continue
        processed_texts.add(row_hash)

        # --- 3. 解析 [经济数据] ---
        if current_section == 'DATA':
            # 典型结构: Time | Country | Name | Importance(maybe empty) | Actual | Forecast | Previous
            # 但是列数不固定 (发布前/发布后不同)
            # 我们从两头往中间凑
            
            event_time = cols[0]
            country = cols[1] if len(cols) > 1 else "全球"
            
            # 指标名称通常是比较长的那一段
            name = cols[2] if len(cols) > 2 else "未知指标"
            
            # 尝试提取数值，数值通常在末尾，且包含数字、%、B、M、K
            values = []
            for col in reversed(cols):
                # 如果包含数字或者是 "--"
                if re.search(r'\d|--', col) and len(col) < 15:
                    values.append(col)
                else:
                    # 一旦遇到非数值（比如指标名），就停止倒序查找
                    if len(values) >= 3: # 通常最多3个数值 (公布, 预测, 前值)
                        break
            
            # 倒序回来的，所以要反转回去: [前值, 预测, 公布]
            # 但金十的顺序通常是: 前值 | 预测值 | 公布值 (或者布局顺序不同)
            # 网页视觉顺序通常是: 指标 ... 前值 预测 公布
            # 提取到的 values 列表现在是倒序的 [公布, 预测, 前值]
            
            prev = "--"
            forecast = "--"
            actual = "--"
            
            if len(values) >= 1: actual = values[0]
            if len(values) >= 2: forecast = values[1]
            if len(values) >= 3: prev = values[2]
            
            # 构建事件
            evt = Event()
            evt.name = f"🇺🇳[{country}] {name}"
            
            # 设置时间
            hm = event_time.split(':')
            start_dt = datetime(
                current_date.year, current_date.month, current_date.day,
                int(hm[0]), int(hm[1]), tzinfo=pytz.timezone('Asia/Shanghai')
            )
            evt.begin = start_dt
            evt.duration = timedelta(minutes=15)
            
            evt.description = (
                f"【经济数据】\n"
                f"国家/地区: {country}\n"
                f"指标名称: {name}\n"
                f"------------------\n"
                f"前值: {prev}\n"
                f"预测: {forecast}\n"
                f"公布: {actual}\n"
            )
            events.append(evt)
            print(f"    [数据] {event_time} {name}")

        # --- 4. 解析 [财经大事] ---
        elif current_section == 'EVENT':
            # 典型结构: Time | Country | City/Person | Event Content
            event_time = cols[0]
            country = cols[1] if len(cols) > 1 else ""
            
            # 剩下的合并为事件内容
            content_parts = cols[2:]
            content = " ".join(content_parts)
            
            evt = Event()
            evt.name = f"📢[{country}] {content[:15]}..." # 标题不宜太长
            
            hm = event_time.split(':')
            start_dt = datetime(
                current_date.year, current_date.month, current_date.day,
                int(hm[0]), int(hm[1]), tzinfo=pytz.timezone('Asia/Shanghai')
            )
            evt.begin = start_dt
            evt.duration = timedelta(minutes=30)
            
            evt.description = (
                f"【财经大事】\n"
                f"国家: {country}\n"
                f"时间: {event_time}\n"
                f"事件: {content}\n"
            )
            events.append(evt)
            print(f"    [大事] {event_time} {content[:10]}")

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
                time.sleep(5) # 等待加载
                
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

    # 保存文件
    if total_count > 0:
        output_file = 'economic_calendar.ics'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(cal.serialize())
        print(f"\n成功生成 {output_file}，包含 {total_count} 个结构化数据。")
    else:
        print("\n未获取到数据。")

if __name__ == "__main__":
    run_scraper()
