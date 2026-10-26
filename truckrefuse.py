from http_client import http_get
import re
import json
import base64
from datetime import datetime, timedelta
import pytz

TRUCKREFUSE_CHANNELS = {
    "hd1": "https://truckrefuse.net/e/nnqs0pp1tjmh9",
    "hd2": "https://truckrefuse.net/e/qq0n9rnpa6u34",
    "h3": "https://truckrefuse.net/e/ppw1o2f9i086",
    "h4": "https://truckrefuse.net/e/llevsxsu5f3ky",
    "hd5": "https://truckrefuse.net/e/iirhxz37r7caa",
    "hd6": "https://truckrefuse.net/e/nnpsmhv1tfe6c",
    "hd7": "https://truckrefuse.net/e/33zqtrg0w9f0p",
    "hd8": "https://truckrefuse.net/e/wwy9780tox0wj",
    "hd9": "https://truckrefuse.net/e/mmhfpigjx4ytn",
    "hd10": "https://truckrefuse.net/e/7763yclzqvk9t",
    "hd11": "https://truckrefuse.net/e/dd56lmtc4ssep",
    "br1": "https://truckrefuse.net/e/ooim08ch7hgii",
    "br2": "https://truckrefuse.net/e/99tb387o87q1h",
    "b3": "https://truckrefuse.net/e/yyvt6eq490ie0",
    "br4": "https://truckrefuse.net/e/1195j4obyjsef",
    "br5": "https://truckrefuse.net/e/55bceick2pl6y",
    "br6": "https://truckrefuse.net/e/ppw1h2d9m1kji",
    "sporttv1": "https://truckrefuse.net/e/hh7jwlo3y79bg",
    "sporttv2": "https://truckrefuse.net/e/66czvp08uk3ub",
    "sporttv3": "https://truckrefuse.net/e/xxgwrm5ynaa3y",
    "sporttv4": "https://truckrefuse.net/e/33zqtkx0wfzdd",
    "sporttv5": "https://truckrefuse.net/e/qq0nol2pvddok",
    "eleven1": "https://truckrefuse.net/e/zz804qoxh624n",
    "eleven2": "https://truckrefuse.net/e/55bce6ukbgc8e",
    "eleven3": "https://truckrefuse.net/e/bbokqapm0qfol",
    "btv": "https://truckrefuse.net/e/uun2kr9s62koo",
}

TRUCKREFUSE_CHANNELS.setdefault("hd3", TRUCKREFUSE_CHANNELS["h3"])
TRUCKREFUSE_CHANNELS.setdefault("hd4", TRUCKREFUSE_CHANNELS["h4"])
TRUCKREFUSE_CHANNELS.setdefault("br3", TRUCKREFUSE_CHANNELS["b3"])


def wrap_iframe(url):
    b64 = base64.b64encode(url.encode()).decode().rstrip("=")
    return f"https://multi.govoet.cc/?iframe={b64}"


def parse_truckrefuse():
    url = "https://sportsonline.st/prog.txt"
    try:
        response = http_get(url, timeout=15, retries=2)
        response.raise_for_status()
        try:
            response.encoding = 'utf-8'
        except Exception:
            pass
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

    lines = response.text.split('\n')
    matches = []

    london_tz = pytz.timezone('Europe/London')
    jakarta_tz = pytz.timezone('Asia/Jakarta')

    current_date_str = None
    days_map = {
        'MONDAY': 0, 'TUESDAY': 1, 'WEDNESDAY': 2, 'THURSDAY': 3,
        'FRIDAY': 4, 'SATURDAY': 5, 'SUNDAY': 6
    }
    line_regex = re.compile(r'^(\d{2}:\d{2})\s+(.*?)\s+\|\s+(https?://.*)$')

    today = datetime.now(london_tz).date()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.upper() in days_map:
            day_idx = days_map[line.upper()]
            today_idx = today.weekday()
            days_ahead = day_idx - today_idx
            if days_ahead < 0:
                days_ahead += 7
            current_date_obj = today + timedelta(days=days_ahead)
            current_date_str = current_date_obj.strftime("%Y-%m-%d")
            continue
        if not current_date_str:
            continue
        match = line_regex.match(line)
        if match:
            time_str, content, url = match.groups()
            url = url.strip()

            league = ""
            team1 = ""
            team2 = ""

            if ':' in content:
                parts = content.split(':', 1)
                league = parts[0].strip()
                match_info = parts[1].strip()
            else:
                match_info = content

            if ' x ' in match_info or ' X ' in match_info:
                sep = ' X ' if ' X ' in match_info else ' x '
                teams = match_info.split(sep)
                team1 = teams[0].strip()
                team2 = teams[1].strip()
            elif ' vs ' in match_info or ' VS ' in match_info:
                sep = ' VS ' if ' VS ' in match_info else ' vs '
                teams = match_info.split(sep)
                team1 = teams[0].strip()
                team2 = teams[1].strip()
            elif ' @ ' in match_info:
                teams = match_info.split(' @ ')
                team1 = teams[0].strip()
                team2 = teams[1].strip()
            else:
                team1 = match_info.strip()

            def clean_name(name):
                return re.sub(r'[^a-zA-Z0-9]', '', name)

            id_str = f"{clean_name(team1)}-{clean_name(team2)}" if team2 else clean_name(team1)

            try:
                dt_str = f"{current_date_str} {time_str}"
                dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                dt_obj = london_tz.localize(dt_obj)
                dt_jakarta = dt_obj.astimezone(jakarta_tz)
                kickoff_date = dt_jakarta.strftime("%Y-%m-%d")
                kickoff_time = dt_jakarta.strftime("%H:%M")
            except ValueError:
                continue

            ss_match = re.search(r'/([^/]+)\.php$', url)
            if not ss_match:
                continue
            channel = ss_match.group(1).lower()
            tr_url = TRUCKREFUSE_CHANNELS.get(channel)
            if not tr_url:
                continue

            server_data = {
                "url": wrap_iframe(tr_url),
                "label": "CH-?"
            }

            match_data = {
                "id": id_str,
                "league": league,
                "team1": {"name": team1, "logo": ""},
                "team2": {"name": team2, "logo": ""},
                "kickoff_date": kickoff_date,
                "kickoff_time": kickoff_time,
                "match_date": "",
                "match_time": kickoff_time,
                "duration": "3.5",
                "servers": [server_data]
            }
            matches.append(match_data)

    merged_matches = {}
    for m in matches:
        m_id = m['id']
        if m_id in merged_matches:
            merged_matches[m_id]['servers'].extend(m['servers'])
        else:
            merged_matches[m_id] = m

    final_list = []
    for m in merged_matches.values():
        seen = set()
        uniq = []
        for s in m['servers']:
            if s['url'] not in seen:
                seen.add(s['url'])
                uniq.append(s)
        m['servers'] = uniq
        for idx, srv in enumerate(m['servers']):
            srv['label'] = f"CH-{idx+1}"
        final_list.append(m)

    return final_list


if __name__ == "__main__":
    data = parse_truckrefuse()
    with open('truckrefuse.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(data)} matches to truckrefuse.json")
