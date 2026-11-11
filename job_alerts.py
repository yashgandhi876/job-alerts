#!/usr/bin/env python3
"""Poll job sources, keep Java + Spring Boot roles in Pune / Remote India /
Remote Global, and send new ones to WhatsApp through CallMeBot.

Standard library only. Usage:
    python3 job_alerts.py --dry-run     # print matches, send nothing, save nothing
    python3 job_alerts.py               # send to WhatsApp and update state/seen.json

Environment:
    CALLMEBOT_PHONE, CALLMEBOT_APIKEY   required to send
    ADZUNA_APP_ID, ADZUNA_APP_KEY       optional, adds India-wide coverage
"""
import argparse
import concurrent.futures as cf
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state", "seen.json")
UA = {"User-Agent": "Mozilla/5.0 (personal job-alert script)", "Accept": "*/*"}
NOW = time.time()

with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as fh:
    CFG = json.load(fh)

TITLE_OK = re.compile(CFG["title_must_match"], re.I)
TITLE_BAD = re.compile(CFG["title_must_not_match"], re.I)
TITLE_OTHER_STACK = re.compile(CFG["title_other_stack"], re.I)
TITLE_JAVA = re.compile(r"\bjava\b(?!\s*-?\s*script)|spring|j2ee", re.I)
SENIOR_TITLE =re.compile(r"senior|\bsr\b|lead|staff|principal|architect|\b(ii|iii|iv)\b|\b[2-4]\b", re.I)

JAVA = re.compile(r"\bjava\b(?!\s*-?\s*script)|\bj2ee\b", re.I)
SPRING = re.compile(
    r"spring[\s-]*boot|spring\s+(?:framework|mvc|cloud|data|security|webflux|batch)"
    r"|java\W{1,6}spring\b|\bspring\W{1,6}java\b",
    re.I,
)
EXTRAS = [
    ("React", re.compile(r"\breact(?:\.?js)?\b", re.I)),
    ("SQL", re.compile(r"\b(?:sql|mysql|postgres(?:ql)?|oracle)\b", re.I)),
    ("Microservices", re.compile(r"micro-?services", re.I)),
    ("AWS", re.compile(r"\baws\b", re.I)),
    ("Kafka", re.compile(r"\bkafka\b", re.I)),
]
YEARS = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*)?(?:years?|yrs?)\b", re.I
)
REMOTE_WORD = re.compile(r"remote|anywhere|worldwide|global|work from home|\bwfh\b|distributed", re.I)
GLOBAL_WORD = re.compile(r"worldwide|anywhere|global|\bworld\b|international", re.I)
APAC_WORD = re.compile(r"\bapac\b|asia", re.I)
TAGS = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------- helpers
def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url, timeout=25):
    return json.loads(http_get(url, timeout))


def strip_html(text):
    if not text:
        return ""
    text = html.unescape(html.unescape(str(text)))
    return re.sub(r"\s+", " ", TAGS.sub(" ", text)).strip()


def to_epoch(value):
    """Accept epoch seconds, epoch millis, ISO-8601 or RFC-822; return seconds or None."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e11 else float(value)
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def classify_location(text, remote=False):
    """Return 'Pune', 'Remote (India)', 'Remote (Global)', 'Remote (APAC)' or None."""
    low = (text or "").lower()
    if "pune" in low:
        return "Pune"
    if not (remote or REMOTE_WORD.search(low)):
        return None
    if "india" in low:
        return "Remote (India)"
    leftover = re.sub(r"remote|[\W_]+", "", low)
    if GLOBAL_WORD.search(low) or not leftover:
        return "Remote (Global)"
    if APAC_WORD.search(low):
        return "Remote (APAC)"
    return None


def best_location(candidates, remote=False):
    labels = [classify_location(c, remote) for c in candidates if c is not None]
    labels = [label for label in labels if label]
    for wanted in ("Pune", "Remote (India)", "Remote (Global)", "Remote (APAC)"):
        if wanted in labels:
            return wanted
    return None


def title_ok(title):
    return bool(TITLE_OK.search(title)) and not TITLE_BAD.search(title)


def job(source, jid, title, company, where, url, text, posted, trusted_stack=False):
    return {
        "id": f"{source}:{jid}",
        "source": source,
        "title": " ".join((title or "").split()),
        "company": " ".join((company or "").split()),
        "where": where,
        "url": url,
        "text": text or "",
        "posted": posted,
        "trusted_stack": trusted_stack,
    }


# ---------------------------------------------------------------- remote boards
def src_remoteok():
    out = []
    for item in get_json("https://remoteok.com/api?tag=java"):
        if "position" not in item:
            continue
        loc = item.get("location") or ""
        where = classify_location(loc, remote=True)
        text = " ".join(item.get("tags") or []) + " " + strip_html(item.get("description"))
        out.append(job("RemoteOK", item["id"], item["position"], item.get("company"), where,
                       item.get("url"), text, to_epoch(item.get("epoch"))))
    return out


def src_remotive():
    out = []
    data = get_json("https://remotive.com/api/remote-jobs?search=java")
    for item in data.get("jobs", []):
        where = classify_location(item.get("candidate_required_location"), remote=True)
        text = " ".join(item.get("tags") or []) + " " + strip_html(item.get("description"))
        out.append(job("Remotive", item["id"], item["title"], item.get("company_name"), where,
                       item.get("url"), text, to_epoch(item.get("publication_date"))))
    return out


def src_jobicy():
    out = []
    data = get_json("https://jobicy.com/api/v2/remote-jobs?count=50&tag=java")
    for item in data.get("jobs", []):
        where = classify_location(item.get("jobGeo"), remote=True)
        text = strip_html(item.get("jobDescription"))
        out.append(job("Jobicy", item["id"], item["jobTitle"], item.get("companyName"), where,
                       item.get("url"), text, to_epoch(item.get("pubDate"))))
    return out


def src_himalayas():
    out, seen_ids = [], set()
    urls = [
        "https://himalayas.app/jobs/api/search?q=java%20spring%20boot&page=1",
        "https://himalayas.app/jobs/api/search?q=java%20spring%20boot&page=2",
        "https://himalayas.app/jobs/api?limit=20",
    ]
    for url in urls:
        try:
            data = get_json(url)
        except Exception as exc:  # one page failing should not lose the others
            print(f"  himalayas page failed: {exc}", file=sys.stderr)
            continue
        for item in data.get("jobs", []):
            jid = item.get("guid") or item.get("applicationLink")
            if not jid or jid in seen_ids:
                continue
            seen_ids.add(jid)
            restrictions = item.get("locationRestrictions") or []
            where = classify_location(", ".join(restrictions) or "Worldwide", remote=True)
            text = strip_html(item.get("description"))
            out.append(job("Himalayas", jid, item["title"], item.get("companyName"), where,
                           item.get("applicationLink") or jid, text, to_epoch(item.get("pubDate"))))
    return out


def src_wwr():
    out = []
    feeds = [
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    ]
    for feed in feeds:
        root = ET.fromstring(http_get(feed))
        for item in root.iter("item"):
            def field(name):
                node = item.find(name)
                return (node.text or "").strip() if node is not None else ""
            raw_title = field("title")
            company, _, title = raw_title.partition(": ")
            if not title:
                company, title = "", raw_title
            country, region = field("country"), field("region")
            where = classify_location(country or region, remote=True)
            text = field("skills") + " " + strip_html(field("description"))
            link = field("link") or field("guid")
            out.append(job("WeWorkRemotely", field("guid") or link, title, company, where,
                           link, text, to_epoch(field("pubDate"))))
    return out


# ---------------------------------------------------------------- Adzuna (optional)
def src_adzuna(state):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    gap = CFG["adzuna"]["min_minutes_between_runs"] * 60
    if NOW - state["meta"].get("adzuna_last", 0) < gap:
        return []
    state["meta"]["adzuna_last"] = NOW
    out = []
    for query in CFG["adzuna"]["queries"]:
        params = {
            "app_id": app_id, "app_key": app_key, "results_per_page": 50,
            "what": query["what"], "sort_by": "date", "max_days_old": CFG["max_age_days"],
        }
        if query.get("where"):
            params["where"] = query["where"]
        url = "https://api.adzuna.com/v1/api/jobs/in/search/1?" + urllib.parse.urlencode(params)
        for item in get_json(url).get("results", []):
            title = strip_html(item.get("title"))
            text = strip_html(item.get("description"))
            loc = (item.get("location") or {}).get("display_name", "")
            remote = bool(REMOTE_WORD.search(title + " " + text))
            where = classify_location(loc, remote=remote)
            # Adzuna only returns a short snippet, so the search query stands in for the stack check.
            out.append(job("Adzuna", item["id"], title, (item.get("company") or {}).get("display_name"),
                           where, item.get("redirect_url"), title + " " + text,
                           to_epoch(item.get("created")), trusted_stack=True))
    return out


# ---------------------------------------------------------------- company career boards
def src_greenhouse(board, state, budget):
    out = []
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
    max_age = CFG["max_age_days"] * 86400
    for item in data.get("jobs", []):
        jid = f"Greenhouse:{board}/{item['id']}"
        title = item.get("title", "")
        where = classify_location((item.get("location") or {}).get("name", ""))
        if not where or not title_ok(title):
            continue
        posted = to_epoch(item.get("first_published")) or to_epoch(item.get("updated_at"))
        if jid in state["seen"] or (posted and NOW - posted > max_age):
            continue
        if budget["left"] <= 0:
            continue
        budget["left"] -= 1
        try:
            detail = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{item['id']}")
        except Exception:
            continue
        company = detail.get("company_name") or board.title()
        out.append(job("Greenhouse", f"{board}/{item['id']}", title, company, where,
                       item.get("absolute_url"), strip_html(detail.get("content")), posted))
    return out


def src_lever(board, state, budget):
    out = []
    for item in get_json(f"https://api.lever.co/v0/postings/{board}?mode=json"):
        cats = item.get("categories") or {}
        locations = [cats.get("location")] + list(cats.get("allLocations") or [])
        where = best_location(locations, remote=item.get("workplaceType") == "remote")
        title = item.get("text", "")
        if not where or not title_ok(title):
            continue
        lists = " ".join(strip_html(part.get("content")) for part in item.get("lists") or [])
        text = " ".join([item.get("descriptionPlain") or "", lists, item.get("additionalPlain") or ""])
        out.append(job("Lever", f"{board}/{item['id']}", title, board.title(), where,
                       item.get("hostedUrl"), text, to_epoch(item.get("createdAt"))))
    return out


def src_ashby(board, state, budget):
    out = []
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    for item in data.get("jobs", []):
        if item.get("isListed") is False:
            continue
        locations = [item.get("location")] + [
            sec.get("location") for sec in item.get("secondaryLocations") or []
        ]
        where = best_location(locations, remote=bool(item.get("isRemote")))
        title = item.get("title", "")
        if not where or not title_ok(title):
            continue
        text = item.get("descriptionPlain") or strip_html(item.get("descriptionHtml"))
        out.append(job("Ashby", f"{board}/{item['id']}", title, board.title(), where,
                       item.get("jobUrl"), text, to_epoch(item.get("publishedAt"))))
    return out


# ---------------------------------------------------------------- matching
def required_years(text):
    """Highest 'N years' figure in the posting, with the top of its range if given."""
    best = None
    for match in YEARS.finditer(text):
        low = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else None
        if low > 15 or (high is not None and high < low):
            continue
        if best is None or low > best[0]:
            best = (low, high)
    return best


def evaluate(item):
    """Return (True, details) for a match, else (False, reason)."""
    if not item["where"]:
        return False, "location"
    if not title_ok(item["title"]):
        return False, "title"
    # A title that names another primary stack (and not Java) is not a Java role,
    # even if the description lists Java somewhere.
    if TITLE_OTHER_STACK.search(item["title"]) and not TITLE_JAVA.search(item["title"]):
        return False, "other-stack title"
    blob =item["title"] + " " + item["text"]
    if not item["trusted_stack"] and not (JAVA.search(blob) and SPRING.search(blob)):
        return False, "stack"

    exp = CFG["experience"]
    years = required_years(blob)
    if years:
        low, high = years
        if low > exp["candidate_max_years"]:
            return False, f"asks {low}+ years"
        if high is not None and high < exp["candidate_min_years"]:
            return False, f"asks {low}-{high} years"
        if (high is None and low < exp["reject_if_job_asks_less_than"]
                and not SENIOR_TITLE.search(item["title"])):
            return False, f"asks only {low}+ years"

    stack = ["Java", "Spring Boot"] + [name for name, rx in EXTRAS if rx.search(blob)]
    exp_label = ""
    if years:
        exp_label = f"{years[0]}-{years[1]} yrs" if years[1] else f"{years[0]}+ yrs"
    return True, {"stack": stack, "experience": exp_label}


def dedupe_key(item):
    norm = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
    return f"key:{norm(item['company'])}|{norm(item['title'])}|{item['where']}"


def ago(posted):
    if not posted:
        return ""
    minutes = max(0, int((NOW - posted) / 60))
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 1440:
        return f"{minutes // 60}h ago"
    return f"{minutes // 1440}d ago"


def format_message(item, details):
    lines = [f"🆕 *{item['title']}*"]
    if item["company"]:
        lines.append(f"🏢 {item['company']}")
    lines.append(f"📍 {item['where']} · via {item['source']}")
    lines.append("🧩 " + ", ".join(details["stack"]))
    meta = " · ".join(part for part in (details["experience"], ago(item["posted"])) if part)
    if meta:
        lines.append(f"🕒 {meta}")
    lines.append(f"🔗 {item['url']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- WhatsApp
def send_whatsapp(text):
    phone, key = os.environ.get("CALLMEBOT_PHONE"), os.environ.get("CALLMEBOT_APIKEY")
    if not (phone and key):
        raise RuntimeError("CALLMEBOT_PHONE and CALLMEBOT_APIKEY are not set")
    query = urllib.parse.urlencode({"phone": phone, "text": text, "apikey": key})
    try:
        body = http_get("https://api.callmebot.com/whatsapp.php?" + query, timeout=40)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"CallMeBot HTTP {exc.code}: {exc.read()[:200]!r}") from None
    reply = body.decode("utf-8", "replace")
    if re.search(r"apikey is invalid|error|not (?:found|valid|registered)", reply, re.I) and \
            "queued" not in reply.lower():
        raise RuntimeError(f"CallMeBot rejected the message: {strip_html(reply)[:200]}")


# ---------------------------------------------------------------- state
def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            state = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("seen", {})
    state.setdefault("meta", {})
    return state


def save_state(state):
    cutoff = NOW - 45 * 86400
    state["seen"] = {k: v for k, v in sorted(state["seen"].items()) if v >= cutoff}
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=0, sort_keys=True)
        fh.write("\n")


def mark(state, key):
    # Refresh at most once a day so the state file does not change on every run.
    if NOW - state["seen"].get(key, 0) > 86400:
        state["seen"][key] = int(NOW)


# ---------------------------------------------------------------- main
def collect(state):
    budget = {"left": CFG["max_detail_fetches_per_run"]}
    tasks = [
        ("RemoteOK", src_remoteok), ("Remotive", src_remotive), ("Jobicy", src_jobicy),
        ("Himalayas", src_himalayas), ("WeWorkRemotely", src_wwr),
        ("Adzuna", lambda: src_adzuna(state)),
    ]
    for kind, fn in (("greenhouse", src_greenhouse), ("lever", src_lever), ("ashby", src_ashby)):
        for board in CFG.get(kind, []):
            tasks.append((f"{kind}/{board}", lambda fn=fn, board=board: fn(board, state, budget)))

    jobs, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks}
        for future in cf.as_completed(futures):
            name = futures[future]
            try:
                jobs.extend(future.result())
            except Exception as exc:
                failed.append(f"{name}: {exc}")
    return jobs, failed, len(tasks)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print matches; send and save nothing")
    parser.add_argument("--test-message", action="store_true", help="send one test WhatsApp message and exit")
    parser.add_argument("--verbose", action="store_true", help="show why each new job was rejected")
    parser.add_argument("--max-age-days", type=float, help="override max_age_days from config.json")
    args = parser.parse_args()
    if args.max_age_days:
        CFG["max_age_days"] = args.max_age_days

    if args.test_message:
        send_whatsapp("✅ Job alerts are connected. New Java + Spring Boot roles will arrive here.")
        print("Test message sent.")
        return 0

    state = load_state()
    jobs, failed, source_count = collect(state)
    max_age = CFG["max_age_days"] * 86400

    queue, reasons = [], {}
    for item in jobs:
        key = dedupe_key(item)
        if item["id"] in state["seen"] or key in state["seen"]:
            mark(state, item["id"])
            continue
        ok, info = evaluate(item)
        if ok and item["posted"] and NOW - item["posted"] > max_age:
            ok, info = False, "too old"
        if not ok:
            reasons[info.split(" ")[0]] = reasons.get(info.split(" ")[0], 0) + 1
            if args.verbose:
                print(f"  skip [{info}] {item['source']}: {item['title']} @ {item['company']}")
            mark(state, item["id"])
            continue
        if any(dedupe_key(q[0]) == key for q in queue):
            mark(state, item["id"])
            continue
        queue.append((item, info))

    queue.sort(key=lambda pair: pair[0]["posted"] or 0, reverse=True)
    cap = CFG["max_messages_per_run"]
    sent = 0
    for item, info in queue[:cap]:
        message = format_message(item, info)
        if args.dry_run:
            print("\n" + message)
        else:
            try:
                send_whatsapp(message)
            except Exception as exc:
                print(f"send failed, will retry next run: {exc}", file=sys.stderr)
                break
            time.sleep(2)
        state["seen"][item["id"]] = int(NOW)
        state["seen"][dedupe_key(item)] = int(NOW)
        sent += 1

    print(f"\nsources: {source_count - len(failed)}/{source_count} ok | fetched: {len(jobs)} | "
          f"new matches: {len(queue)} | {'would send' if args.dry_run else 'sent'}: {sent} | "
          f"held for next run: {max(0, len(queue) - sent)}")
    if reasons:
        print("rejected (new only): " + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    for line in failed:
        print(f"source failed: {line}", file=sys.stderr)

    if not args.dry_run:
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
