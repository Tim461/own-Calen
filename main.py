import time
import re
from datetime import datetime, timedelta
import pytz
from ics import Calendar, Event

# 引入浏览器自动化相关库
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def get_html_via_selenium(url):
    print(f"正在启动浏览器访问: {url}")
    
    # 配置无界面浏览器 (Headless Chrome)
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") # 无界面模式
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    # 伪装 User-Agent，防止被识别为机器人
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 安装并启动 Chrome
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    try:
        driver.get(url)
        # 强制等待 10 秒，确保金十的动态数据加载完成
        # 这是一个笨办法，但对于不需要高频抓取的任务最稳定
        print("网页加载中，等待 10 秒...")
        time.sleep(10)
        
        # 获取渲染后的网页源代码
        page_source = driver.page_source
        return page_source
    except Exception as e:
        print(f"浏览器运行出错: {e}")
        return None
    finally:
        driver.quit()

def parse_and_generate_ics(html_content):
    if not html_content:
        print("未获取到网页内容")
        return

    soup = BeautifulSoup(html_content, 'html.parser')
    cal = Calendar()
    count = 0
    
    # 获取当前日期，用于处理只有时间没有日期的事件
    today_date = datetime.now(pytz.timezone('Asia/Shanghai')).date()

    # --- 解析逻辑 ---
    # 金十期货页面的结构经常变，这里使用模糊查找策略
    # 我们查找包含期货交易所名称或特定关键词的行
    
    # 查找所有的表格行或列表项
    # 金十通常使用 div 布局，我们尝试抓取所有包含文本的 div/a/span
    # 这里通过“包含时间格式”的特征来定位事件
    
    # 提取网页中所有可见文本，按行分割
    text_lines = soup.get_text("\n", strip=True).split("\n")
    
    current_date_obj = today_date
    
    for i, line in enumerate(text_lines):
        # 1. 尝试识别日期行 (例如 "2023年10月27日 星期五")
        if "年" in line and "月" in line and "日" in line:
            try:
                # 简单的正则提取日期 202X-XX-XX
                date_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', line)
                if date_match:
                    current_date_obj = datetime(
                        int(date_match.group(1)),
                        int(date_match.group(2)),
                        int(date_match.group(3))
                    ).date()
                    print(f"发现日期分组: {current_date_obj}")
                    continue
            except:
                pass

        # 2. 尝试识别具体事件
        # 期货日历通常包含: [交易所名称] [事件内容]
        # 常见交易所: CFFEX, SHFE, DCE, CZCE, LME, COMEX, NYMEX, INE
        keywords = ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'LME', 'COMEX', 'NYMEX', 'INE', '中金所', '上期所', '大商所', '郑商所', '最后交易日', '到期日', '休市']
        
        if any(kw in line.upper() for kw in keywords):
            # 这是一个潜在的事件行
            event_text = line.strip()
            
            # 过滤掉太短的干扰文本
            if len(event_text) < 4: 
                continue

            # 创建事件
            evt = Event()
            evt.name = event_text
            evt.begin = current_date_obj
            evt.make_all_day() # 期货事件通常是全天
            evt.description = f"来源: 金十期货\n原文: {event_text}"
            
            cal.events.add(evt)
            count += 1
            print(f"添加事件: [{current_date_obj}] {event_text}")

    # 保存文件
    if count > 0:
        with open('futures.ics', 'w', encoding='utf-8') as f:
            f.writelines(cal.serialize())
        print(f"成功生成 futures.ics，共包含 {count} 个事件")
    else:
        print("警告: 未解析到任何事件。可能是页面结构发生了剧烈变化。")
        # 调试用：保存网页源码看看到底抓到了什么
        # with open('debug.html', 'w', encoding='utf-8') as f:
        #    f.write(soup.prettify())

if __name__ == "__main__":
    url = "https://qihuo.jin10.com/calendar.html#/"
    html = get_html_via_selenium(url)
    parse_and_generate_ics(html)
