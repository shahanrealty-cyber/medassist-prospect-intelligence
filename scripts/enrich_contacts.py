#!/usr/bin/env python3
"""Enrich EMS prospect records with evidence-backed public contact research candidates.

Uses Bing RSS search results as discovery only. It never guesses a person's name,
email, or phone. Human verification is required before contact details are treated as verified.
"""
import json, re, time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

DATA_PATH = "national-prospects.json"
MAX_PER_RUN = 20
USER_AGENT = "Mozilla/5.0 (compatible; MedAssistContactResearch/1.0)"
ROLE_TERMS = [
    '"EMS" "quality improvement" director contact',
    '"EMS" "clinical quality" chief contact',
    '"patient care report" EMS QA manager',
    '"EMS medical director" official staff directory',
]
OFFICIAL_HINTS = (".gov", ".us", "municode.com")
BLOCKED_HOSTS = ("microsoft.com", "live.com", "office.com", "cloud.microsoft", "wikipedia.org", "facebook.com", "youtube.com", "google.com", "bing.com")
JUNK_TITLE_TERMS = ("sign in", "sign into", "create your account", "college", "university", "wikipedia")

def text(el, tag):
    node = el.find(tag)
    return (node.text or "").strip() if node is not None else ""

def officialish(url):
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(".gov") or host.endswith(".us") or any(h in host for h in OFFICIAL_HINTS)

def relevant_result(item, agency):
    url = item.get("url", "")
    title = item.get("title", "").lower()
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
        return False
    if any(term in title for term in JUNK_TITLE_TERMS):
        return False
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", agency) if len(t) > 3 and t.lower() not in {"department", "county", "rescue", "system"}]
    blob = (item.get("title", "") + " " + item.get("description", "") + " " + url).lower()
    context_terms = ("fire rescue", "fire department", "ems", "emergency medical", "ambulance", "quality improvement", "clinical quality", "staff directory", "leadership", "medical director", "chief")
    return any(term in blob for term in terms) and any(term in blob for term in context_terms)

def fetch_rss(query):
    url = "https://www.bing.com/search?format=rss&q=" + quote(query)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=20) as response:
        root = ET.fromstring(response.read())
    items = []
    for item in root.findall(".//item")[:8]:
        title, link, desc = text(item, "title"), text(item, "link"), text(item, "description")
        if title and link:
            items.append({"title": title, "url": link, "description": re.sub(r"<[^>]+>", " ", desc)})
    return items

def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    leads = data.get("leads", [])
    candidates = [x for x in leads if x.get("agency") and not x.get("agency", "").startswith("Research lead:") and (not x.get("contactResearchUpdatedAt") or any(not relevant_result(r, x.get("agency", "")) for r in x.get("contactResearchResults", [])))]
    candidates.sort(key=lambda x: (0 if "baseline" not in (x.get("category") or "").lower() else 1, x.get("agency", "")))
    now = datetime.now(timezone.utc).isoformat()
    enriched, errors = 0, []
    for lead in candidates[:MAX_PER_RUN]:
        agency = lead["agency"]
        state = (lead.get("state") or "").strip()
        agency_clean = re.sub(r"[^A-Za-z0-9 &'-]", " ", agency).strip()
        queries = [
            '"' + agency_clean + '" ' + state + ' fire rescue leadership official',
            '"' + agency_clean + '" ' + state + ' EMS quality improvement contact',
            '"' + agency_clean + '" ' + state + ' staff directory fire rescue',
        ]
        results = []
        for query in queries:
            try:
                results.extend(fetch_rss(query))
                time.sleep(0.5)
            except Exception as exc:
                errors.append(agency + ": " + type(exc).__name__)
        # Filter irrelevant destinations first, then prefer official sources.
        seen, results2 = set(), []
        filtered = [r for r in results if relevant_result(r, agency)]
        for result in sorted(filtered, key=lambda r: (not officialish(r["url"]), r["url"])):
            if result["url"] not in seen:
                seen.add(result["url"])
                results2.append(result)
        lead["bestContact"] = lead.get("bestContact", "")
        lead["bestContactTitle"] = lead.get("bestContactTitle", "") or "Target role: EMS QA/QI or clinical quality leader"
        lead["bestContactEmail"] = lead.get("bestContactEmail", "")
        lead["bestContactPhone"] = lead.get("bestContactPhone", "")
        lead["bestContactSource"] = lead.get("bestContactSource", "")
        lead["bestContactConfidence"] = "Role recommendation only" if not lead.get("bestContact") else lead.get("bestContactConfidence", "Needs verification")
        lead["contactResearchQuery"] = " | ".join(queries)
        lead["contactResearchResults"] = results2[:5]
        lead["contactResearchUpdatedAt"] = now
        lead["contactResearchStatus"] = "Candidate sources found; verify agency match and identify a named contact" if results2 else "No usable search results; manual research required"
        if results2:
            enriched += 1
    data["last_contact_research_run_utc"] = now
    data["last_contact_research_checked"] = min(len(candidates), MAX_PER_RUN)
    data["last_contact_research_filter_version"] = 2
    data["last_contact_research_with_results"] = enriched
    data["last_contact_research_errors"] = errors[:10]
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Contact research completed.")
    print("Prospects searched:", min(len(candidates), MAX_PER_RUN))
    print("Prospects with search results:", enriched)
    print("Errors:", len(errors))
    print("Note: search results are candidates, not verified contacts.")

if __name__ == "__main__":
    main()
