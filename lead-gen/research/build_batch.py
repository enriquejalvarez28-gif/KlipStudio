"""Merge raw research JSON into one CRM import batch with scores and DMs."""
import json, glob, os, sys

RAW = sys.argv[1]
OUT = sys.argv[2]

ORDER = ["pembroke_miramar.json", "weston_davie.json", "plantation.json", "ftl_a.json", "ftl_b.json"]

GEO = {"Pembroke Pines": 20, "Miramar": 18, "Weston": 18, "Davie": 18, "Plantation": 16, "Fort Lauderdale": 14}
FIT = {"local": 20, "regional": 14, "national/multi-office": 6}

T = [
    "Hi {g}, came across {firm} while looking at local injury firms. I'm with Klip Media in Pembroke Pines; we do video content and digital marketing for professional practices. {hook} Would you be open to hearing it?",
    "Hey {g}! I'm with Klip Media / Klip Studio here in Pembroke Pines. We produce video and handle marketing for law firms and other professional practices in Broward. {hook} Mind if I share it?",
    "Hi {g}, quick note from a neighbor: I'm with Klip Media in Pembroke Pines (marketing agency with our own production studio). {hook} Open to hearing the idea?",
]

# key (substring of business name) -> overrides. Facts in hooks come only from the research snippets.
O = {
 "Lawlor, White": dict(city="Fort Lauderdale", g="John", fit=14,
    hook="Since you have offices from Pembroke Pines to Weston and Plantation, I had an idea for short location-specific videos so each office has its own local content.",
    svc="On-location video at each office + location-specific Reels / local SEO",
    note="One firm, several offices: HQ 2211 Davie Blvd, Fort Lauderdale; also Pembroke Pines (8362 Pines Blvd #410), Weston (3014 Indian Trace #164), Plantation (1802 N University Dr #212). Founder named as John K. Lawlor in some snippets; another snippet names Andrew Winston and John Lawlor."),
 "Romelus": dict(g="there",
    hook="I had an idea for a couple of short educational videos on what people should do after an accident, filmed at our studio a few minutes from your office.",
    svc="Attorney intro video + educational short-form videos", fit=16,
    note="Only an Avvo listing found; practice also covers real estate. Confirm the firm is active."),
 "Demos": dict(g="Andrew", t=0,
    hook="I saw you've been handling injury cases since 1999, and I had an idea for a few short videos where you walk people through the first days after an accident.",
    svc="Attorney-led educational video series + Instagram Reels",
    note="'Since 1999' per a Martindale snippet. Possible Spanish (abogado.com listing, unconfirmed). No firm website found in results."),
 "Dickstein": dict(g="Mark", t=1,
    hook="Since your firm serves clients in English, Spanish and Creole, I had an idea for a short multilingual video series on common accident questions.",
    svc="Multilingual (EN/ES/Creole) short-form educational videos",
    note="No phone in results. No firm website confirmed (dicksteinpa.com belongs to an unrelated Tampa firm)."),
 "Garnes": dict(g="Erika", t=2, ig="https://www.instagram.com/garnesinjurylaw", igs="Third-party listing only – Needs Verification",
    hook="Since you work with clients in English and Spanish, I had an idea for a short bilingual series answering the questions people have right after a car accident.",
    svc="Bilingual (EN/ES) educational Reels + attorney personal-branding video",
    note="Instagram handle appears on a third-party Geebo listing, not on the firm site; confirm before messaging. Two phone numbers listed across directories."),
 "Rafael Gonzalez": dict(g="Rafael", t=1,
    hook="I had an idea for a few short videos explaining the accident-claim process in plain language, recorded at our studio right here in Pembroke Pines.",
    svc="Educational short-form videos + Google Business Profile optimization",
    note="Website sosrafa.com comes from the Avvo profile (attorney listed as Rafael Angel Gonzalez-Farina)."),
 "Justice Beyond": dict(g="Tyler", t=0, fit=16,
    hook="Since you handle both criminal defense and injury cases, I had an idea for short 'what to do next' videos for each, which tend to work well as Reels.",
    svc="Short-form 'know your rights' / 'what to do next' Reels",
    note="Primarily criminal defense; personal injury is secondary. Still a Priority-1 legal target."),
 "Crenshaw": dict(g="Andre", t=2,
    hook="Since you run your own practice, I had an idea for a simple personal-brand video series featuring you answering common injury-claim questions.",
    svc="Personal branding video series + Instagram Reels",
    note="Directory: solo practice established 1998. Website from a directory listing."),
 "Pierre Legal": dict(g="Edna", t=1,
    hook="Since you serve clients in English and Haitian Creole, I had an idea for a short bilingual video series on accident claims for the Miramar community.",
    svc="Bilingual (EN/Haitian Creole) educational videos + Reels",
    note="Shares address 3350 SW 148th Ave Ste 110 with Floyd-Clarke Legal and Robert Rivera Law; probably a shared or virtual office."),
 "McKinnon": dict(g="Christina", t=0, fit=16,
    hook="I had an idea for a few short educational videos across your family-law and injury work, filmed at our studio close to your Miramar office.",
    svc="Educational video series (family law + PI) + Reels",
    note="Primarily family law (~70%), PI ~20%. A press release mentions a video release; check for existing video content."),
 "Floyd-Clarke": dict(g="Easter", t=2, fit=16,
    hook="I had an idea for a short video series explaining estate-planning basics and what to do after an injury, which tends to work well for educating local families.",
    svc="Educational video series (estate planning + PI)",
    note="Primarily estate planning; PI is secondary. Shares a suite address with Pierre Legal and Robert Rivera Law. Phone from a third-party ranking site."),
 "Robert Rivera": dict(g="Robert", t=1, fit=10,
    hook="I had an idea for a few short videos on workers' comp and accident claims, which people search for a lot.",
    svc="Educational workers' comp / PI videos",
    note="Location unconfirmed: Justia/Avvo place attorney Robert M. Rivera in Miami Lakes. Shares a Miramar suite address with two other firms."),
 "Baker Legal": dict(g="Robert", t=0,
    hook="Since you have offices across South Florida, I had an idea for location-specific short videos for your Weston office.",
    svc="Location-specific video + Reels",
    note="Main office Boca Raton (2255 Glades Rd); Weston is a branch. Firm domain not shown in results."),
 "David Law": dict(g="there", t=1,
    hook="Since your team works in English, Spanish, French and Haitian Creole, I had an idea for a multilingual short-video series on accident claims.",
    svc="Multilingual educational short-form videos",
    note="Directory: est. 2013, 3 attorneys. Domain from a directory listing."),
 "Turchin": dict(g="Jason", t=2,
    hook="I had an idea for a few short FAQ-style videos you could record at our studio, a few minutes from your Weston office.",
    svc="FAQ video series + Instagram Reels",
    note="Also lists Miami, Key West and Orlando offices. Phone numbers differ across directories. Firm domain not shown in results."),
 "Sobol": dict(g="Scott", t=0,
    hook="I had an idea for a couple of short educational videos on accident and nursing-home cases, recorded at our studio near your Davie office.",
    svc="Attorney-led educational videos + Reels",
    note="Directory info conflicts on phone/suite. Firm domain not shown in results. Decision maker inferred from firm name only (not stated as owner), so left blank."),
 "Schiller Kessler": dict(g="Marc", t=1,
    hook="I noticed your site has Davie-specific pages, like the one on State Road 7 accidents, and I had an idea for turning local topics like that into short videos.",
    svc="Local-topic short-form videos + local SEO / GEO",
    note="Snippets from the firm domain show Davie-specific practice pages."),
 "Rosen Injury": dict(city="Davie", g="Eric", t=2,
    hook="Since you have offices in Davie and Fort Lauderdale, I had an idea for a short attorney-led video series you could use across both.",
    svc="Attorney-led educational video series",
    note="Offices in Davie (5599 S University Dr #206) and Fort Lauderdale (5353 N Federal Hwy #101); which one is HQ is unclear."),
 "VP Law": dict(g="Vanessa", t=0,
    hook="Since you work in English and Spanish and handle PIP and homeowner claims, I had an idea for short bilingual explainers on those topics.",
    svc="Bilingual (EN/ES) explainer Reels",
    note="Single attorney; 'led by' Vanessa N. Perez per directory. Domain from a directory listing."),
 "McCullough": dict(g="Scott", t=1,
    hook="I had an idea for a couple of on-location educational videos we could film right at your Davie office.",
    svc="On-location video production + Reels",
    note="Alternate phone (954) 361-2916. Firm domain not shown in results."),
 "South Florida Trial": dict(g="there", t=2, fit=16,
    hook="Since you handle both injury and criminal cases, I had an idea for short 'what to do next' videos for each.",
    svc="Short-form educational videos",
    note="Also criminal defense / DUI. Firm domain not shown in results."),
 "Lipsky": dict(g="Joseph", t=0,
    hook="I saw you've been representing injured clients for over 30 years, and I had an idea for a short Q&A video series built on that experience.",
    svc="Attorney Q&A video series + Reels",
    note="Avvo lists a different Plantation address; confirm. Firm domain not shown in results."),
 "Cohen & Juda": dict(g="there", t=1,
    hook="I had an idea for a few short attorney videos on common injury questions, filmed at our studio just down the road from Plantation.",
    svc="Attorney intro + educational videos",
    note="Harvey M. Cohen and partner Gary H. Juda named in snippets, but no founder/owner title stated. Domain from a directory."),
 "Lyons & Snyder": dict(g="there", t=2,
    hook="Since your team serves Spanish-speaking clients, I had an idea for a short bilingual video series on accident claims.",
    svc="Bilingual (EN/ES) educational videos",
    note="Led by Marc P. Lyons and Philip M. Snyder (no owner title stated). Suite numbers conflict across sources."),
 "Chalik": dict(g="Jason", t=0,
    hook="I had an idea for a few on-location videos at your Plantation office that could also work as Reels.",
    svc="On-location video + Reels",
    note="Large multi-office firm (Justia lists ~20 offices); may have in-house marketing. Firm domain not shown in results."),
 "VG Law": dict(g="there", t=1,
    hook="Since your team works in English and Spanish, I had an idea for a short bilingual explainer series on accident claims.",
    svc="Bilingual (EN/ES) educational Reels",
    note="Attorneys listed: Sabrina Visram, Omar Giraldo, Krystal Gage (no owner title stated). Only one source."),
 "Kelsky": dict(g="there", t=2,
    hook="I had an idea for a couple of short educational videos on injury and mold/toxic-tort cases, which are topics people search for.",
    svc="Educational video series",
    note="Alternate address 1250 S Pine Island Rd Ste 250 in FindLaw/Law.com; confirm."),
 "Saban": dict(g="Ariel", t=0,
    hook="Since your team has grown to several attorneys, I had an idea for a set of short attorney intro videos so people can put a face to each lawyer.",
    svc="Attorney intro videos for the team + Reels",
    note="Est. 2007, ~9 attorneys per snippets. Decision maker from an Avvo snippet; confirm."),
 "Frisch": dict(g="there", t=1, fit=14,
    hook="I had an idea for a few short educational videos on product-liability and injury questions.",
    svc="Educational video series",
    note="Weakest record: directory evidence only, no website, phone or attorney names found."),
 "Kogan": dict(g="there", t=2,
    hook="", svc="(Low fit: statewide firm)",
    note="Statewide firm (~11 offices); a July 2026 Datanyze item says it is renaming to Baker & DiSalvo. Likely in-house marketing."),
 "Anidjar": dict(g="there", t=0,
    hook="I had an idea for a few short educational videos for your Fort Lauderdale office that could also run as Reels.",
    svc="Educational videos + Reels",
    note="Regional firm; blog posts on the firm domain (e.g. a Fort Lauderdale crane accident post)."),
 "Blakeley": dict(g="Jarrett", t=1,
    hook="Since you have offices across Florida, I had an idea for a short video series built around your Fort Lauderdale office.",
    svc="Location-specific video + Reels",
    note="Offices also in Miami, West Palm Beach and Jacksonville. Domain from a Boca Raton Observer profile."),
 "Santa Maria": dict(city="Davie", g="Diana", t=2,
    hook="I had an idea for a short attorney-led video series you could film at our studio a few minutes from your office.",
    svc="Personal branding / attorney-led video series",
    note="Address 5220 S University Dr (33328) is in Davie; Best Lawyers lists Davie HQ, other directories say Fort Lauderdale. Practice since 1991 per snippets. Regional."),
 "Dolinsky": dict(g="Robert", t=0,
    hook="Since your firm serves clients in English and Spanish, I had an idea for a bilingual short-video series on accident claims.",
    svc="Bilingual (EN/ES) educational Reels",
    note="Founding year conflicts (2004 vs 2007). Domain from a Datanyze directory. No phone found in results."),
 "Englander": dict(g="Gary", t=1,
    hook="I had an idea for a couple of short educational videos featuring you and Warren that could work as Instagram Reels.",
    svc="Attorney-led educational Reels",
    note="Two conflicting Fort Lauderdale addresses in directories."),
 "Fazio": dict(g="Vivian", t=2,
    hook="Since you serve Spanish-speaking clients, I had an idea for a short bilingual series on accident claims.",
    svc="Bilingual (EN/ES) educational Reels + website review",
    note="Firm website not identified in results; addresses/phones conflict (also a Sunrise office)."),
 "Hollander": dict(g="there", t=0,
    hook="I had an idea for a few short educational videos for your Fort Lauderdale office that could also work as Reels.",
    svc="Educational videos + Reels",
    note="Also a West Palm Beach office. Gregg M. Hollander listed with 25+ years, but no owner title stated."),
 "Kelley": dict(g="Bob", t=1, fit=14,
    hook="I saw the announcements about new trial attorneys joining the team, and I had an idea for short attorney intro videos to go with them.",
    svc="Attorney intro videos + Reels",
    note="Larger trial firm (co-founded 2006); may have in-house or agency marketing."),
 "Krupnick": dict(g="there", t=2, fit=14,
    hook="I had an idea for a short video series built around your firm's long history in Fort Lauderdale.",
    svc="Brand/history video + attorney series",
    note="Founded 1974 by Jon Krupnick; DM placed on 'there' because the current decision maker is unclear. Address conflicts across directories."),
 "Madalon": dict(g="Joseph", t=0,
    hook="I had an idea for a couple of short educational videos on accident and brain-injury cases that could work as Reels.",
    svc="Educational Reels",
    note="Joseph Madalon is the lead attorney, but the snippets don't call him the founder. Nolo lists by-appointment offices elsewhere."),
 "Eskander": dict(g="there", t=1, fit=8,
    hook="", svc="(Hold: firm status unclear)",
    note="Address listed in Hollywood FL; co-founder Maikel Eskander has left. Confirm the firm still exists before any outreach."),
 "Schlesinger": dict(g="Scott", t=2,
    hook="Since your firm has been in Fort Lauderdale for decades, I had an idea for a short video series that tells that story and puts the attorneys on camera.",
    svc="Brand story video + attorney series",
    note="Firm history of 60+ years per snippets; Owler lists 1-25 employees."),
 "Wolf & Pravato": dict(g="there", t=0,
    hook="I had an idea for a few short educational videos that could work both on your site and as Reels.",
    svc="Educational videos + Reels",
    note="Founded 1993; regional. Richard Pravato named as Senior Attorney."),
 "Yeboah": dict(g="there", t=1,
    hook="I had an idea for a short attorney-led video series you could film at our studio.",
    svc="Attorney-led video series",
    note="Main office Fort Lauderdale; also Miami and Key West. Firm domain not shown in results."),
 "Workman": dict(g="Devon", t=2,
    hook="I had an idea for a few short 'what to do after a crash' videos featuring you that could work well as Reels.",
    svc="Attorney-led educational Reels",
    note="Offices in Fort Lauderdale and Clermont."),
 "Weinstein": dict(g="Justin", t=0,
    hook="I saw the WPTV segment you sponsor and had an idea for turning that kind of content into short Instagram Reels.",
    svc="Short-form repurposing of existing video + Reels",
    note="Offices in Fort Lauderdale, West Palm Beach, Orlando and Naples; sponsors a WPTV segment. Firm domain not shown in results."),
 "Schilling": dict(g="there", t=1,
    hook="I had an idea for a couple of short educational videos on car, motorcycle and bicycle accidents that could work as Reels.",
    svc="Educational Reels",
    note="Aaron D. Silvers and Jeremy T. Schilling listed; Avvo also lists a Hialeah office. Phone differs on Justia."),
 "Tucker Law": dict(g="there", t=2, fit=16,
    hook="I had an idea for a few short educational videos that could go with your blog and city pages.",
    svc="Video to pair with existing blog/city pages + Reels",
    note="Also handles patents/trademarks. Public email Info@TuckerUp.com."),
 "Schneider": dict(g="Justin", t=0,
    hook="I saw you're a former felony prosecutor, and I had an idea for a short video series built around that perspective on injury cases.",
    svc="Personal branding video series",
    note="Former felony prosecutor per snippets. No phone or website in results."),
 "Ruggiero": dict(g="William", t=1,
    hook="I had an idea for a short attorney-led video series you could film at our studio.",
    svc="Attorney-led video series",
    note="Nolo profile only; board certified in civil trial law per Nolo. Name inferred from firm name; no owner title stated."),
}

def match(name):
    for k, v in O.items():
        if k.lower() in name.lower():
            return v
    raise SystemExit("no override for " + name)

seen, out = set(), []
for fn in ORDER:
    for x in json.load(open(os.path.join(RAW, fn))):
        o = match(x["business_name"])
        key = id(o)
        if key in seen:
            continue
        seen.add(key)
        city = o.get("city", x["city"])
        if "Lawlor" in x["business_name"]:
            x["address"] = "2211 Davie Blvd, Fort Lauderdale, FL (HQ)"
        if "Rosen" in x["business_name"]:
            x["address"] = "5599 S University Dr, Suite 206, Davie, FL"
        ig = o.get("ig", x.get("instagram_url", ""))
        igs = o.get("igs", "Needs Verification")
        dm_name = x.get("decision_maker", "")
        phone_or_email = bool(x.get("phone") or x.get("public_email"))
        geo = GEO.get(city, 0)
        fit = o.get("fit", FIT.get(x.get("firm_type"), 14))
        content = 12
        contact = (4 if ig else 0) + (4 if dm_name else 0) + (3 if phone_or_email else 0)
        total = geo + 20 + content + fit + contact
        dm = ""
        if total >= 60 and o["hook"]:
            short = x["business_name"].split(" (")[0]
            dm = T[o.get("t", 0)].format(g=o["g"], firm=short, city=city, hook=o["hook"])
        note = (f"Geo {geo}/20 ({city}); Industry 20/20 (Priority-1 legal); Content 12/25 neutral – website and Instagram "
                f"not reviewed (network blocked), so no evidence either way; Fit {fit}/20 ({x.get('firm_type')}); "
                f"Contact {contact}/15 (IG {'candidate' if ig else 'not found'}, decision maker {'named' if dm_name else 'not found'}, "
                f"phone/email {'yes' if phone_or_email else 'no'}).")
        out.append({
            "Business Name": x["business_name"], "Industry": "Legal – Personal Injury", "City": city,
            "Address": x.get("address", ""), "Website": x.get("website", "").split(" (")[0],
            "Phone": x.get("phone", ""), "Instagram URL": ig, "Instagram Status": igs,
            "Decision Maker": dm_name, "Public Business Email": x.get("public_email", ""),
            "Firm Type": x.get("firm_type", ""),
            "Score Geo": geo, "Score Industry": 20, "Score Content": content, "Score Fit": fit, "Score Contact": contact,
            "Score Note": note,
            "Content Opportunity": "Unreviewed – needs manual check of website video and Instagram activity. Idea: " + o["svc"],
            "Recommended Service": o["svc"], "Personalized DM": dm,
            "Notes": "Verification: search results only. " + o["note"] + " Snippet notes: " + x.get("website_observations", ""),
            "Source URLs": " | ".join(x.get("source_urls", [])),
        })
json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
print(len(out), "leads")
