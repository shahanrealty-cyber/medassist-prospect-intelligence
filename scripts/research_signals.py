#!/usr/bin/env python3
"""Collect candidate EMS/ambulance buying signals from Google News RSS.
All newly discovered items are stored as unverified research leads until a human validates them.
"""
import json, os, re, time, hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

DATA_PATH = "national-prospects.json"
QUERIES = [
    ('EMS QA/QI', '"EMS" ("quality improvement" OR "quality assurance" OR CQI)'),
    ('ePCR procurement', '("ePCR" OR "electronic patient care report") (RFP OR solicitation OR procurement OR contract) EMS'),
    ('EMS billing/documentation', 'EMS ambulance (documentation OR "medical necessity" OR reimbursement OR billing) audit'),
    ('EMS leadership', 'EMS ("quality improvement" OR "clinical quality") (director OR chief OR manager)'),
    ('EMS grant/funding', 'EMS fire rescue grant funding quality improvement data'),
    ('Ambulance RFP', 'ambulance service EMS RFP contract award 2026'),
    ('EMS accreditation', 'EMS agency accreditation quality improvement 2026'),
    ('private ambulance', '"ambulance" "quality assurance" OR "clinical quality" provider'),
]
MAX_ITEMS_PER_QUERY = 12

def get_text(el, tag):
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""

def load_data():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("leads"), list):
            return data
    return {"dataset_name":"MedAssist National Prospect Database","version":datetime.now(timezone.utc).date().isoformat(),"leads":[]}

def key_for(item):
    return re.sub(r"\W+", " ", (item.get("agency","") + " " + item.get("signal","")).lower()).strip()

def main():
    data = load_data()
    leads = data["leads"]
    existing_urls = {x.get("source","").strip() for x in leads if x.get("source")}
    existing_keys = {key_for(x) for x in leads}
    added = 0
    errors = []
    now = datetime.now(timezone.utc).isoformat()
    for category, query in QUERIES:
        url = "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-US&gl=US&ceid=US:en"
        try:
            req = Request(url, headers={"User-Agent":"MedAssistProspectResearch/1.0 (public RSS reader)"})
            with urlopen(req, timeout=20) as response:
                xml = response.read()
            root = ET.fromstring(xml)
            for item in root.findall(".//item")[:MAX_ITEMS_PER_QUERY]:
                title = get_text(item, "title")
                link = get_text(item, "link")
                pubdate = get_text(item, "pubDate")
                source_el = item.find("source")
                publisher = ((source_el.text or "").strip() if source_el is not None else "")
                if not title or not link or link in existing_urls:
                    continue
                published_at = ""
                if pubdate:
                    try:
                        published_at = parsedate_to_datetime(pubdate).date().isoformat()
                    except (TypeError, ValueError, OverflowError):
                        published_at = ""
                lead = {
                    "id": "rss-" + hashlib.sha256(link.encode("utf-8")).hexdigest()[:16],
                    "agency": "Research lead: " + title[:180],
                    "state": "",
                    "providerType": "Public / private EMS research",
                    "category": category,
                    "triggerQuery": query,
                    "triggerTerms": category,
                    "triggerEvidence": "Headline: " + title + ((" | Publisher: " + publisher) if publisher else "") + ". Discovery clue only, not proof of buying intent.",
                    "sourceType": "Search result / aggregator",
                    "publishedAt": published_at,
                    "agencyMatchConfidence": "Low",
                    "validationStatus": "Needs review",
                    "validationReason": "Not yet reviewed. Confirm the original source, agency/provider identity, publication date, and whether the evidence supports the claimed signal.",
                    "medassistRelevance": "",
                    "lastValidatedAt": "",
                    "signal": title + ((" | Publisher: " + publisher) if publisher else ""),
                    "why": "Candidate public-news signal discovered by hourly RSS search. Validate the underlying article, identify the actual agency/provider, and confirm relevance before outreach.",
                    "contact": "Identify EMS leadership / QA-QI / clinical quality / procurement",
                    "nextStep": "Open source, verify agency and date, confirm signal, then create or merge into the correct account record.",
                    "source": link,
                    "confidence": "Needs validation",
                    "status": "Research",
                    "signalDate": pubdate,
                    "notes": "AUTOMATED CANDIDATE, NOT VERIFIED. Trigger category: " + category + ". Exact search query: " + query + ". Collected at " + now + ". Publisher: " + publisher + ". The headline may not identify a buyer or demonstrate purchase intent. Open and validate source before outreach."
                }
                k = key_for(lead)
                if k in existing_keys:
                    continue
                leads.append(lead)
                existing_urls.add(link)
                existing_keys.add(k)
                added += 1
        except Exception as e:
            errors.append(category + ": " + str(e))
    data["version"] = datetime.now(timezone.utc).date().isoformat()
    data["last_research_run_utc"] = now
    data["last_research_added"] = added
    data["last_research_errors"] = errors[:8]
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Research run complete. New candidate records:", added)
    print("Total records:", len(leads))
    print("Feed errors:", len(errors))
    for error in errors:
        print("FEED ERROR:", error)

if __name__ == "__main__":
    main()
