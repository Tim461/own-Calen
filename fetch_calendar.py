import requests
import ics
from datetime import datetime

def fetch_events(url):
    response = requests.get(url)
    response.raise_for_status()  # Raise an error for bad responses
    return response.json()

def create_ical(events, filename):
    calendar = ics.Calendar()
    
    for event in events:
        e = ics.Event()
        e.name = event['title']
        e.begin = datetime.fromisoformat(event['start'])
        e.end = datetime.fromisoformat(event['end'])
        e.description = event.get('description', 'No Description')
        e.location = event.get('location', 'No Location')
        calendar.events.add(e)

    with open(filename, 'w') as f:
        f.write(str(calendar))

def main():
    urls = [
        "http://ics.wallstreetcn.com/global.json",
        "http://ics.wallstreetcn.com/china.json"
    ]
    
    for idx, url in enumerate(urls):
        events = fetch_events(url)
        create_ical(events, f"calendar_{idx + 1}.ics")

if __name__ == "__main__":
    main()