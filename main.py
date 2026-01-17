import requests
import json
from ics import Calendar, Event
from datetime import datetime, timedelta
import pytz
import sys

# --- 配置区域 ---
# 金十期货日历通常按日期分文件存储
# 格式示例: https://cdn.jin10.com/dc/reports/dc_futures_event_20231027.json
# 如果你发现自动抓取失败，请在浏览器F12->Network中找到以 .json 结尾的请求，
# 将其 URL 规律复制到这里。
BASE_URL_TEMPLATE = "https://cdn.jin10.com/dc/reports/dc_futures_event_{date}.json"

def fetch_data(date_str):
    url = BASE_URL_TEMPLATE.format(date=date_str)
    print(f"正在尝试抓取: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://qihuo.jin10.com/',
        'Origin': 'https://qihuo.jin10.com'
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"请求失败 (Status {resp.status_code}) - 该日期可能无数据或URL规则已变")
            return []
    except Exception as e:
        print(f"请求异常: {e}")
        return []

def generate_calendar():
    cal = Calendar()
    
    # 抓取今天及未来7天的数据
    today = datetime.now(pytz.timezone('Asia/Shanghai'))
    
    for i in range(8):
        current_day = today + timedelta(days=i)
        date_str = current_day.strftime('%Y%m%d') # 格式化为 20231027
        
        events = fetch_data(date_str)
        
        if not events:
            continue
            
        # 金十期货日历通常返回一个列表，包含多个类别的事件
        # 结构可能为: [{'date': '...', 'event_content': '...', 'country': '...'}]
        # 注意：不同接口返回字段可能不同，需做容错
        
        for item in events:
            try:
                # 过滤掉非重要数据（可选）
                
                evt = Event()
                
                # 提取标题
                # 金十字段多变，这里列举常见字段名
                title = item.get('event_content') or item.get('name') or item.get('title') or '未命名期货事件'
                exchange = item.get('exchange_name') or item.get('country') or ''
                
                # 组合标题
                evt.name = f"[{exchange}] {title}"
                
                # 处理时间
                # 接口通常返回 "2023-10-27" 或具体时间戳
                event_date_str = item.get('date') or item.get('public_date')
                if not event_date_str:
                    continue
                
                # 如果只有日期没有时间，设为全天事件
                # 如果有具体时间（如 21:00），解析它
                # 这里简单处理为全天事件，因为期货交割日、最后交易日通常是全天性质
                dt_start = datetime.strptime(event_date_str, '%Y-%m-%d')
                evt.begin = dt_start
                evt.make_all_day()
                
                # 描述信息
                detail = item.get('remark') or item.get('detail') or ''
                evt.description = f"交易所: {exchange}\n日期: {event_date_str}\n备注: {detail}\n来源: 金十期货"
                
                cal.events.add(evt)
                
            except Exception as e:
                print(f"解析单条数据出错: {e}, 数据: {item}")
                continue

    # 保存文件
    output_file = 'futures.ics'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(cal.serialize())
    print(f"日历生成完毕: {output_file}")

if __name__ == "__main__":
    generate_calendar()
