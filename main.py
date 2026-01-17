import requests
import json
from ics import Calendar, Event
from datetime import datetime, timedelta
import pytz

def fetch_and_generate(url, output_file):
    print(f"开始获取数据: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"获取数据失败: {e}")
        return

    # 创建日历对象
    cal = Calendar()

    # 华尔街见闻的JSON数据通常在一个列表里，或者嵌套在 'data' 字段中
    # 这里做兼容处理
    events_data = data if isinstance(data, list) else data.get('data', [])

    count = 0
    for item in events_data:
        try:
            e = Event()
            
            # 提取事件名称 (title)
            title = item.get('TITLE', item.get('title', '未知财经事件'))
            country = item.get('COUNTRY', item.get('country', ''))
            
            # 根据重要性加星标 (通常 importance 为 1-3)
            importance = item.get('IMPORTANCE', item.get('importance', 1))
            stars = '★' * int(importance)
            
            e.name = f"[{country}] {stars} {title}"

            # 提取时间戳 (timestamp)
            timestamp = item.get('TIMESTAMP', item.get('timestamp'))
            if timestamp:
                # 转换为 UTC 时间
                dt = datetime.fromtimestamp(int(timestamp), pytz.utc)
                e.begin = dt
                # 财经事件通常是瞬间发布的，默认设置 15 分钟时长
                e.end = dt + timedelta(minutes=15)

            # 提取描述信息 (前值、预测值等)
            prev = item.get('PREVIOUS', item.get('previous', '-'))
            consensus = item.get('CONSENSUS', item.get('consensus', '-'))
            actual = item.get('ACTUAL', item.get('actual', '-'))
            
            e.description = f"重要性: {stars}\n" \
                            f"国家: {country}\n" \
                            f"前值: {prev}\n" \
                            f"预期: {consensus}\n" \
                            f"实际: {actual}\n" \
                            f"数据来源: 华尔街见闻"

            cal.events.add(e)
            count += 1
        except Exception as e:
            print(f"解析单个事件失败: {e}")
            continue

    # 保存为 .ics 文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(cal.serialize())
    
    print(f"成功生成 {output_file}，包含 {count} 个事件。")

if __name__ == "__main__":
    # 处理全球日历
    fetch_and_generate('http://ics.wallstreetcn.com/global.json', 'global.ics')
    # 处理中国日历
    fetch_and_generate('http://ics.wallstreetcn.com/china.json', 'china.ics')
