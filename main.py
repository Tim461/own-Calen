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

# --- 指定你要抓取的这4个日期 ---
TARGET_DATES = [
    "2026-01-14",
    "2026-01-15",
    "2026-01-16",
    "2026-01-20"
]
# -----------------------------

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

def is_value_column(text):
    """判断一列是否像是一个数值（前值/预测/公布）"""
    # 特征：长度短，包含数字，或者就是 '--'
    # 排除纯文字（除非是非常短的状态描述）
    if len(text) > 15: return False # 数值通常不会这么长
    if "--" in text: return True
    if re.search(r'\d', text): return True # 包含数字
    if text in ["待定", "无", "休市"]: return True
    return False

def parse_day_content(html_content, current_date):
    events = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 查找所有行容器
    rows = soup.find_all(['div', 'tr', 'li'])
    
    mode = "UNKNOWN"
    processed_hashes = set()

    for row in rows:
        # 使用 | 分割保持列结构
        row_str = row.get_text("|", strip=True)
        
        # 去重
        h = hash(row_str)
        if h in processed_hashes: continue
        processed_hashes.add(h)

        # 1. 识别 【经济数据一览】 板块
        if "经济数据一览" in row_str and len(row_str) < 30:
            mode = "DATA"
            print(f"  -> 进入 [经济数据] 区域")
            continue
        elif "财经大事一览" in row_str or "期货日历" in row_str:
            # 遇到其他板块，立即停止，防止混淆
            mode = "OTHER" 
            continue
            
        # 我们只关心 DATA 模式，且行里不能有表头
        if mode != "DATA": continue
        if "时间" in row_str and "前值" in row_str: continue

        # 2. 拆分列
        cols = [c.strip() for c in row_str.split('|') if c.strip()]
        if not cols: continue

        # 过滤：第一列必须是时间 HH:MM
        if not re.match(r'^\d{2}:\d{2}$', cols[0]): continue

        # === 核心逻辑：三段式夹击法 ===
        # 目标：提取 [时间, 国家, 指标名称, (重要性), 前值, 预测, 公布]
        
        # A. 定左边 (Left Anchor)
        # cols[0] 肯定是 时间
        # cols[1] 通常是 国家 (如果缺失可能直接是名字，但金十通常都有国家)
        time_str = cols[0]
        country = cols[1]
        
        # B. 定右边 (Right Anchor)
        # 从最后的一列往回看，收集所有的“数值列”
        # 我们预期最多找3个数值 (公布, 预测, 前值)
        values_found = [] # 存 [公布, 预测, 前值] (倒序)
        
        # 从列表末尾开始向前扫描
        scan_index = len(cols) - 1
        while scan_index > 1: # 也就是不能扫到国家那一列
            val = cols[scan_index]
            if is_value_column(val):
                values_found.append(val)
                scan_index -= 1
            else:
                # 一旦遇到一个不像数值的东西（大概率是指标名称的末尾，或者重要性），停止扫描
                break
        
        # 还原数值顺序 (前值, 预测, 公布)
        # 现在的 values_found 是倒序的，例如 ['3.4%', '3.5%', '3.6%'] -> 对应 [公布, 预测, 前值]
        # 或者 ['--', '3.5%', '3.6%']
        
        prev, forecast, actual = "--", "--", "--"
        
        # 根据找到的数值数量进行填充
        # 金十的标准顺序是: ... 前值 | 预测 | 公布
        if len(values_found) >= 1: actual = values_found[0]
        if len(values_found) >= 2: forecast = values_found[1]
        if len(values_found) >= 3: prev = values_found[2]
        
        # C. 剩中间 (The Indicator Name)
        # 中间的部分就是：从 Country 之后 (index 2)，到 values_found 之前 (scan_index)
        # 注意：这里可能包含“重要性”（星星），通常表现为空白字符或者"高/中/低"文字
        # 我们把中间剩下的所有文本拼起来，就是名字
        
        name_parts = cols[2 : scan_index + 1]
        # 清洗名字：去掉可能混进来的“高”“中”“低”或者星星符号
        raw_name = " ".join(name_parts)
        
        # 提取完名字，必须确保名字存在
        if not raw_name.strip(): 
            continue # 如果没有名字，这行数据无效

        # 构造事件
        evt = Event()
        evt.name = f"📊[{country}] {raw_name}"
        
        # 时间解析
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
            f"指标: {raw_name}\n"
            f"----------------\n"
            f"前值: {prev}\n"
            f"预测: {forecast}\n"
            f"公布: {actual}\n"
        )
        
        events.append(evt)
        print(f"    + [抓取成功] {time_str} {country} {raw_name} | 前:{prev} 预:{forecast} 公:{actual}")

    return events

def run_scraper():
    cal = Calendar()
    driver = get_driver()
    if not driver: exit(1)

    try:
        base_url = "https://qihuo.jin10.com/calendar.html#/"
        total_count = 0

        # 遍历用户指定的 4 个日期
        for date_str in TARGET_DATES:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            full_url = f"{base_url}{date_str}"
            
            print(f"\n=== 处理日期: {date_str} ===")
            print(f"访问: {full_url}")
            
            try:
                driver.get(full_url)
                # 等待久一点，因为哈希跳转可能不刷新页面，需要给Vue反应时间
                time.sleep(8) 
                
                html = driver.page_source
                day_events = parse_day_content(html, target_date)
                
                for e in day_events:
                    cal.events.add(e)
                    total_count += 1
                    
                if not day_events:
                    print(f"    [-] 该日期下未发现【经济数据一览】内容")

            except Exception as e:
                print(f"    [!] 页面处理出错: {e}")

    except Exception as e:
        print(f"致命错误: {traceback.format_exc()}")
    finally:
        driver.quit()

    # 保存
    if total_count > 0:
        output_file = 'jin10_data_specific.ics'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(cal.serialize())
        print(f"\n全部完成！生成文件: {output_file} (共 {total_count} 条数据)")
    else:
        print("\n未抓取到任何数据。")

if __name__ == "__main__":
    run_scraper()
