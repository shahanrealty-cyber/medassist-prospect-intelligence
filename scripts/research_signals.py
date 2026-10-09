#!/usr/bin/env python3
"""Collect candidate EMS/ambulance buying signals from Google News RSS.
All newly discovered items are stored as unverified research leads until a human validates them.
"""
import json, os, re, hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree as ET

DATA_PATH = "national-prospects.json"
MAX_ITEMS_PER_QUERY = 12
MAX_AGE_DAYS = 180
RELEVANCE_TERMS = re.compile(
    r"\b(ems|ambulance|paramedic|fire rescue|fire department|patient care report|epcr|ePCR|"
    r"quality improvement|quality assurance|clinical quality|medical necessity|billing|"
    r"reimbursement|documentation|cq[i]?|procurement|solicitation|grant|accreditation)\b",
    re.I,
)
AGENCY_HINTS = re.compile(
    r"^(.{2,100}?)\s+(?:announces|awarded|awards|selects|selected|seeks|seeking|"
    r"issues|issued|approves|approved|launches|launched|hires|hired|appoints|appointed|"
    r"receives|received|opens|opened|plans|planned|to receive|to hire|to launch)\b",
    re.I,
)
OFFICIAL_HOST_HINTS = (".gov", ".us", ".state.", "municode.com", "publicpurchase.com", "bonfirehub.com", "bidnetdirect.com")

QUERIES = [
    ('EMS QA/QI', '"EMS" ("quality improvement" OR "quality assurance" OR CQI)'),
    ('ePCR procurement', '("ePCR" OR "electronic patient care report") (RFP OR solicitation OR procurement OR contract) EMS'),
    ('EMS billing/documentation', 'EMS ambulance (documentation OR "medical necessity" OR reimbursement OR billing) audit'),
    ('EMS leadership', 'EMS ("quality improvement" OR "clinical quality") (director OR chief OR manager)'),
    ('EMS grant/funding', 'EMS fire rescue grant funding quality improvement data'),
    ('Ambulance RFP', 'ambulance service EMS RFP contract award 2026'),
    ('EMS accreditation', 'EMS agency accreditation quality improvement 2026'),
    ('private ambulance', '"ambulance" ("quality assurance" OR "clinical quality") provider'),
]

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
    # Stable event key avoids treating a title's minor punctuation changes as a new signal.
    text = (item.get("agency", "") + " " + item.get("signal", "")).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()

def parse_date(value):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None

def infer_agency(title):
    """Only suggest an agency when the headline syntax gives a plausible name; never mark it verified."""
    match = AGENCY_HINTS.search(title.strip())
    if not match:
        return "", "Low"
    candidate = match.group(1).strip(" -,:")
    words = candidate.split()
    if len(words) < 2 or len(candidate) > 100:
        return "", "Low"
    generic = {"ems", "ambulance service", "fire rescue", "fire department", "health officials", "officials"}
    if candidate.lower() in generic:
        return "", "Low"
    return candidate, "Low"

def source_kind(url, publisher):
    host = (urlparse(url).hostname or "").lower()
    if host.endswith(".gov") or host.endswith(".us") or any(hint in host for hint in OFFICIAL_HOST_HINTS):
        return "Potential official source; verify ownership"
    if publisher:
        return "News / industry publisher; verify original source"
    return "Search result / aggregator"

def resolve_source(url):
    """Record whether the linked page can be reached and its final URL; this does not validate the claim."""
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MedAssistProspectResearch/1.0)"})
        with urlopen(req, timeout=10) as response:
            final_url = response.geturl()
            status = getattr(response, "status", 200)
            content_type = response.headers.get("Content-Type", "")
            return final_url, "reachable" if 200 <= status < 400 else "http_error", content_type
    except HTTPError as exc:
        return url, "http_" + str(exc.code), ""
    except (URLError, TimeoutError, ValueError) as exc:
        return url, "unreachable: " + type(exc).__name__, ""

def main():
    data = load_data()
    leads = data["leads"]
    existing_urls = {x.get("source", "").strip() for x in leads if x.get("source")}
    existing_keys = {key_for(x) for x in leads}
    added = 0
    skipped_old = 0
    skipped_irrelevant = 0
    errors = []
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    for category, query in QUERIES:
        url = "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-US&gl=US&ceid=US:en"
        try:
            req = Request(url, headers={"User-Agent": "MedAssistProspectResearch/1.0 (public RSS reader)"})
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
                if not RELEVANCE_TERMS.search(title):
                    skipped_irrelevant += 1
                    continue
                published_dt = parse_date(pubdate)
                published_at = published_dt.date().isoformat() if published_dt else ""
                if published_dt and (now_dt - published_dt) > timedelta(days=MAX_AGE_DAYS):
                    skipped_old += 1
                    continue
                agency, agency_match_confidence = infer_agency(title)
                final_url, source_check_status, content_type = resolve_source(link)
                source_url = final_url or link
                if source_url in existing_urls:
                    continue
                lead = {
                    "id": "rss-" + hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16],
                    "agency": agency or "Research lead: " + title[:150],
                    "state": "",
                    "providerType": "Public / private EMS research",
                    "category": category,
                    "triggerQuery": query,
                    "triggerTerms": category,
                    "triggerEvidence": "Headline: " + title + ((" | Publisher: " + publisher) if publisher else "") + ". Discovery clue only, not proof of buying intent.",
                    "sourceType": source_kind(source_url, publisher),
                    "sourceDomain": urlparse(source_url).hostname or "",
                    "sourceCheckStatus": source_check_status,
                    "sourceContentType": content_type,
                    "publishedAt": published_at,
                    "agencyMatchConfidence": agency_match_confidence,
                    "validationStatus": "Needs review",
                    "validationReason": "Automated checks only. Confirm the original source, agency/provider identity, exact claim, publication date, and whether the signal is actionable before outreach.",
                    "medassistRelevance": "",
                    "lastValidatedAt": "",
                    "signal": title + ((" | Publisher: " + publisher) if publisher else ""),
                    "why": "Candidate discovered via Google News RSS. The linked page reachability was checked, but the claim and agency match were not independently verified.",
                    "contact": "Identify EMS leadership / QA-QI / clinical quality / procurement",
                    "nextStep": "Open source, verify agency and date, capture the exact evidence, then merge into the correct account record.",
                    "source": source_url,
                    "confidence": "Needs validation",
                    "status": "Research",
                    "signalDate": published_at,
                    "notes": "AUTOMATED CANDIDATE, NOT VERIFIED. Category: " + category + ". Query: " + query + ". Collected at " + now + ". Publisher: " + publisher + ". Source check: " + source_check_status + ". Reachability is not evidence that the headline's claim is accurate.",
                }
                k = key_for(lead)
                if k in existing_keys:
                    continue
                leads.append(lead)
                existing_urls.add(source_url)
                existing_keys.add(k)
                added += 1
        except Exception as exc:
            errors.append(category + ": " + type(exc).__name__ + ": " + str(exc))
    data["version"] = datetime.now(timezone.utc).date().isoformat()
    data["last_research_run_utc"] = now
    data["last_research_added"] = added
    data["last_research_skipped_old"] = skipped_old
    data["last_research_skipped_irrelevant"] = skipped_irrelevant
    data["last_research_errors"] = errors[:8]
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Research run complete. New candidate records:", added)
    print("Total records:", len(leads))
    print("Skipped old candidates:", skipped_old)
    print("Skipped irrelevant headlines:", skipped_irrelevant)
    print("Feed errors:", len(errors))
    for error in errors:
        print("FEED ERROR:", error)

if __name__ == "__main__":
    main()
