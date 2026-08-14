"""
==========================================================
py tools/classify_batch_aug8.py  --  the 8 August batch
==========================================================

    "yes complete data base. if you remember all data is sorted by you
     in batches wise."
                                -- operator, 8 August 2026

WHAT THIS BATCH IS
------------------
91 stocks that were blocked as "new listing -- awaiting sector
classification". They are NOT new listings -- ALLCARGO, FDC, METRO
BRANDS, HATSUN, KIOCL have traded for years. The label was a
placeholder from a classification run that never finished, and it kept
the bot deaf to them: 14 of the 91 received graded result cards in the
four days to 7 August and the bot had no price feed for any of them.

They all pass his rules: CMP >= Rs 50 and market cap >= Rs 2,000 Cr.

WHY THEY COULD NOT SIMPLY BE SWITCHED ON
----------------------------------------
They were, at 21:31 on 8 August, and core/master_loader.py refused to
load -- so the bot would not have started. Its guard is right:

    "a tradeable stock with no SECTOR silently breaks the
     sector-strength gate"

core/news_impact.py fans a sector event out to every stock in that
sector. A blank label drops the stock out of its peer group; a wrong
one sends a pharma headline into a metals stock's chip. Both are
silent. So sector comes first, subscription second.

WHY NOT FROM NSE
----------------
Checked before asking him to download anything: NSE's index files
(Total Market 750, Microcap 250, Smallcap 250, Midcap 150) do not
contain a single one of these 91. NSE publishes sectors only for index
constituents, and these sit outside all of them.

SAME METHOD AS THE JULY BATCH
-----------------------------
tools/classify_new_listings.py set the pattern and the doctrine:

    "Symbols I could not identify with confidence are DELIBERATELY not
     in this table ... A guessed sector is worse than a blocked stock."

Every value below uses the vocabulary already in the master -- 29
SECTOR values, 12 BUSINESS_TYPE, 3 OWNERSHIP -- so these group with
their real peers instead of inventing a one-stock sector.

Four symbols are deliberately absent: JAYKAY, WINDMACHIN, and any
whose COMPANY NAME field is only the ticker repeated. They stay
SUBSCRIBE = NO with an honest reason.

Order: SECTOR, INDUSTRY, CORE BUSINESS, BUSINESS_TYPE, OWNERSHIP,
       COMMODITY_EXPOSURE, ECONOMIC_SENSITIVITY, KEYWORDS, THEMES

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import shutil
import sys
from datetime import datetime

MASTER = "data/master_stocks.csv"
STAMP = "8 Aug 2026"

AG = "AGRICULTURE & FERTILIZERS"
AU = "AUTOMOBILE"
BS = "BUSINESS SERVICES"
CG = "CAPITAL GOODS"
CB = "CEMENT & BUILDING MATERIALS"
CH = "CHEMICALS"
CD = "CONSUMER DISCRETIONARY"
CDU = "CONSUMER DURABLES"
DV = "DIVERSIFIED"
FS = "FINANCIAL SERVICES"
FM = "FMCG"
HS = "HEALTHCARE SERVICES"
HT = "HOSPITALITY & TOURISM"
IT = "INFORMATION TECHNOLOGY"
IN = "INFRASTRUCTURE"
LG = "LOGISTICS & TRANSPORTATION"
ME = "MEDIA & ENTERTAINMENT"
MM = "METALS & MINING"
PH = "PHARMACEUTICALS"
PU = "POWER & UTILITIES"
RE = "REAL ESTATE"
SU = "SUGAR"
TX = "TEXTILES & APPAREL"

MFR, SVC, EPC, NBFC, DIST = ("MANUFACTURER", "SERVICE PROVIDER",
                             "EPC / CONTRACTOR", "NBFC", "DISTRIBUTOR")
MINE, POW, PLAT = "MINING", "POWER GENERATOR", "PLATFORM"
PVT, MNC, PSU = "PRIVATE", "MNC", "PSU"
NONE = "NONE"
CONS = "CONSUMER DRIVEN"
EXP = "EXPORT ORIENTED"
IMP = "IMPORT DEPENDENT"
GOVT = "GOVERNMENT SPENDING"
RATE = "INTEREST RATE SENSITIVE"
HOUSE = "INTEREST RATE SENSITIVE | HOUSING"
CONS_EXP = "CONSUMER DRIVEN | EXPORT ORIENTED"
CONS_IMP = "CONSUMER DRIVEN | IMPORT DEPENDENT"
GOVT_EXP = "GOVERNMENT SPENDING | EXPORT ORIENTED"

C = {
    # ---------------- capital goods & engineering ----------------
    "AJAXENGG": (CG, "CONSTRUCTION EQUIPMENT", "Self-loading concrete mixers and construction equipment", MFR, PVT, "STEEL | RUBBER", GOVT, "CONCRETE|SLCM|CONSTRUCTION EQUIPMENT", "INFRASTRUCTURE|CAPEX"),
    "ISGEC": (CG, "HEAVY ENGINEERING", "Boilers, pressure vessels and EPC for process plants", MFR, PVT, "STEEL", GOVT_EXP, "BOILERS|EPC|SUGAR PLANT|PRESSURE VESSELS", "CAPEX|ENGINEERING"),
    "BAJEL": (CG, "POWER TRANSMISSION EPC", "Transmission towers and power transmission EPC", EPC, PVT, "STEEL | ALUMINIUM", GOVT, "TRANSMISSION|TOWERS|EPC|BAJAJ", "POWER|CAPEX"),
    "HPL": (CG, "ELECTRICAL EQUIPMENT", "Meters, switchgear and electrical accessories", MFR, PVT, "COPPER | ALUMINIUM | PLASTICS", GOVT, "METERS|SWITCHGEAR|SMART METER", "POWER|CAPEX"),
    "WEL": (CDU, "ELECTRICAL APPLIANCES", "Fans and small electrical appliances", MFR, PVT, "COPPER | STEEL | ALUMINIUM", CONS, "FANS|APPLIANCES|HAVELLS", "CONSUMPTION"),
    "FOSECOIND": (CH, "FOUNDRY CHEMICALS", "Consumables and chemicals for metal casting", MFR, MNC, "STEEL | IRON CASTINGS | COPPER", EXP, "FOUNDRY|CASTING|CONSUMABLES|MNC", "ENGINEERING"),
    "VESUVIUS": (CG, "REFRACTORIES", "Refractories and flow control for steel and foundry", MFR, MNC, "MAGNESITE | DOLOMITE | BAUXITE", GOVT_EXP, "REFRACTORY|STEEL|FLOW CONTROL|MNC", "STEEL|CAPEX"),
    "PENIND": (CG, "ENGINEERED STEEL PRODUCTS", "Precision steel tubes, profiles and engineering products", MFR, PVT, "STEEL", GOVT, "STEEL TUBES|PROFILES|RAILWAYS|SOLAR", "INFRASTRUCTURE|CAPEX"),
    "MBEL": (CG, "PRE-ENGINEERED BUILDINGS", "Pre-engineered steel buildings and solar structures", EPC, PVT, "STEEL", GOVT, "PEB|SOLAR MOUNTING|STRUCTURES", "INFRASTRUCTURE|SOLAR"),
    "TIIL": (DV, "DIVERSIFIED ENGINEERING", "Scaffolding, steel tubes, cotton yarn and drums", MFR, PVT, "STEEL | COTTON", EXP, "SCAFFOLDING|TUBES|YARN|DRUMS", "ENGINEERING|EXPORTS"),
    "CARRARO": (AU, "AUTO COMPONENTS", "Axles and transmission systems for tractors and off-highway", MFR, MNC, "STEEL | ALUMINIUM", "GOVERNMENT SPENDING | EXPORT ORIENTED", "AXLES|TRANSMISSION|TRACTOR|MNC", "AUTO ANCILLARY"),
    "AUTOAXLES": (AU, "AUTO COMPONENTS", "Axles and brakes for commercial vehicles", MFR, PVT, "STEEL | CAST IRON", CONS, "AXLES|BRAKES|CV|KALYANI", "AUTO ANCILLARY"),
    "JTEKTINDIA": (AU, "AUTO COMPONENTS", "Steering systems for passenger and commercial vehicles", MFR, MNC, "STEEL | ALUMINIUM", CONS, "STEERING|JTEKT|MNC", "AUTO ANCILLARY"),
    "RANEHOLDIN": (AU, "AUTO COMPONENTS HOLDING", "Holding company for the Rane auto component group", MFR, PVT, "STEEL | ALUMINIUM", CONS, "RANE|HOLDING|AUTO ANCILLARY", "AUTO ANCILLARY|HOLDING"),
    "STUDDS": (AU, "AUTO ACCESSORIES", "Two-wheeler helmets and riding accessories", MFR, PVT, "PLASTIC / POLYMER", CONS_EXP, "HELMETS|TWO WHEELER|SAFETY", "CONSUMPTION|AUTO ANCILLARY"),

    # ---------------- metals & mining ----------------
    "KIOCL": (MM, "IRON ORE PELLETS", "Iron ore pellets and blast furnace pig iron", MINE, PSU, "IRON ORE | COAL", GOVT_EXP, "PELLETS|IRON ORE|PSU|EXPORTS", "METALS|PSU"),
    "MAITHANALL": (MM, "FERRO ALLOYS", "Ferro manganese and silico manganese alloys", MFR, PVT, "MANGANESE ORE | IRON ORE", GOVT_EXP, "FERRO ALLOYS|MANGANESE|STEEL", "METALS"),
    "SUNFLAG": (MM, "SPECIAL ALLOY STEEL", "Alloy and special steel for auto and engineering", MFR, PVT, "STEEL | IRON ORE | COAL", CONS, "ALLOY STEEL|AUTO GRADE|SPECIAL STEEL", "METALS|AUTO ANCILLARY"),
    "KSL": (MM, "SPECIAL STEEL", "Forging quality alloy steel and pig iron", MFR, PVT, "STEEL | IRON ORE | COKING COAL", CONS, "ALLOY STEEL|FORGING|KALYANI", "METALS|AUTO ANCILLARY"),
    "PRAKASH": (MM, "STEEL & POWER", "Steel, ferro alloys, PVC pipes and captive power", MFR, PVT, "STEEL | IRON ORE | COAL", GOVT, "STEEL|FERRO ALLOYS|PVC|CAPTIVE POWER", "METALS"),
    "HITECH": (MM, "STEEL PIPES", "ERW steel pipes, tubes and structural sections", MFR, PVT, "STEEL", GOVT, "ERW PIPES|STRUCTURAL|SOLAR|WATER", "INFRASTRUCTURE|METALS"),

    # ---------------- pharmaceuticals & healthcare ----------------
    "FDC": (PH, "FORMULATIONS", "Branded formulations, ORS and ophthalmics", MFR, PVT, NONE, CONS, "FORMULATIONS|ORS|ELECTRAL|OPHTHALMIC", "PHARMA|DOMESTIC"),
    "UNICHEMLAB": (PH, "FORMULATIONS", "Generic formulations for domestic and export markets", MFR, PVT, NONE, EXP, "GENERICS|FORMULATIONS|USFDA", "PHARMA|EXPORTS"),
    "ORCHPHARMA": (PH, "API & FORMULATIONS", "Cephalosporin APIs and finished formulations", MFR, PVT, NONE, EXP, "API|CEPHALOSPORIN|ANTIBIOTIC", "PHARMA|API"),
    "PANACEABIO": (PH, "VACCINES & FORMULATIONS", "Vaccines and pharmaceutical formulations", MFR, PVT, NONE, "EXPORT ORIENTED | GOVERNMENT SPENDING", "VACCINES|BIOTECH|FORMULATIONS", "PHARMA|VACCINES"),
    "GUFICBIO": (PH, "FORMULATIONS", "Sterile injectables and lyophilised formulations", MFR, PVT, NONE, EXP, "INJECTABLES|LYOPHILISED|STERILE", "PHARMA|INJECTABLES"),
    "GUJTHEM": (PH, "API INTERMEDIATES", "Fermentation-based API intermediates", MFR, PVT, NONE, EXP, "API INTERMEDIATE|FERMENTATION|RIFAMPICIN", "PHARMA|API"),
    "DCAL": (PH, "CRAMS", "Contract research and manufacturing of APIs", MFR, PVT, NONE, EXP, "CRAMS|CDMO|API|DISHMAN", "PHARMA|CDMO"),
    "ALEMBICLTD": (PH, "API & HOLDING", "APIs and holding stake in Alembic Pharmaceuticals", MFR, PVT, NONE, EXP, "API|ALEMBIC|HOLDING", "PHARMA|HOLDING"),
    "INDRAMEDCO": (HS, "HOSPITALS", "Apollo Indraprastha multi-speciality hospital, Delhi", SVC, PVT, NONE, CONS, "HOSPITAL|APOLLO|DELHI|MULTISPECIALITY", "HEALTHCARE"),

    # ---------------- FMCG & consumer ----------------
    "HATSUN": (FM, "DAIRY", "Milk, curd, ice cream and dairy products", MFR, PVT, "MILK", CONS, "DAIRY|MILK|ICE CREAM|AROKYA", "CONSUMPTION|DAIRY"),
    "GOPAL": (FM, "PACKAGED SNACKS", "Namkeen, wafers and ethnic snacks", MFR, PVT, "EDIBLE OIL | WHEAT", CONS, "SNACKS|NAMKEEN|WAFERS", "CONSUMPTION"),
    "TASTYBITE": (FM, "PACKAGED FOODS", "Ready-to-eat ethnic foods and sauces", MFR, MNC, "GRAIN", CONS_EXP, "READY TO EAT|MARS|ETHNIC FOOD", "CONSUMPTION|EXPORTS"),
    "HNDFDS": (FM, "CONTRACT MANUFACTURING", "Outsourced manufacturing for FMCG brands", MFR, PVT, "PALM OIL | VEGETABLE OIL", CONS, "CONTRACT MANUFACTURING|FMCG|OUTSOURCED", "CONSUMPTION"),
    "GRMOVER": (FM, "RICE PROCESSING", "Basmati rice milling and branded rice exports", MFR, PVT, "RICE | PADDY", CONS_EXP, "BASMATI|RICE|EXPORTS", "AGRI|EXPORTS"),
    "SUNDROP": (FM, "EDIBLE OILS & FOODS", "Edible oils, peanut butter and packaged foods", MFR, PVT, "PALM OIL | SOYBEAN OIL | SUNFLOWER OIL", CONS, "EDIBLE OIL|SUNDROP|PEANUT BUTTER", "CONSUMPTION"),
    "GMBREW": (FM, "ALCOHOLIC BEVERAGES", "Country liquor and Indian made foreign liquor", MFR, PVT, "MOLASSES | GRAIN", CONS, "LIQUOR|IMFL|COUNTRY LIQUOR|MAHARASHTRA", "CONSUMPTION|ALCOBEV"),
    "DALMIASUG": (SU, "SUGAR & ETHANOL", "Sugar, ethanol, power co-generation and distillery", MFR, PVT, "SUGARCANE|GRAIN", GOVT, "SUGAR|ETHANOL|DISTILLERY|COGEN", "SUGAR|ETHANOL"),
    "EVEREADY": (CDU, "BATTERIES & LIGHTING", "Dry cell batteries, flashlights and lighting", MFR, PVT, "ZINC | STEEL | ALUMINIUM", CONS, "BATTERIES|FLASHLIGHT|LIGHTING", "CONSUMPTION"),
    "SYMPHONY": (CDU, "AIR COOLERS", "Residential and industrial air coolers", MFR, PVT, "PLASTIC / POLYMER", CONS, "AIR COOLER|SUMMER|COOLING", "CONSUMPTION"),
    "LAOPALA": (CDU, "GLASS TABLEWARE", "Opalware and crystalware tableware", MFR, PVT, "SILICA SAND | SODA ASH | NATURAL GAS | LIMESTONE", CONS, "OPALWARE|TABLEWARE|DIVA", "CONSUMPTION"),
    "BOROLTD": (CDU, "GLASSWARE & APPLIANCES", "Consumer glassware, opalware and small appliances", MFR, PVT, "SILICA SAND | SODA ASH | NATURAL GAS | LIMESTONE", CONS, "GLASSWARE|OPALWARE|BOROSIL|APPLIANCES", "CONSUMPTION"),
    "BOSCH-HCIL": (CDU, "WATER HEATING", "Water heaters and home comfort products", MFR, MNC, "COPPER | STEEL", CONS, "WATER HEATER|BOSCH|HOME COMFORT|MNC", "CONSUMPTION"),
    "FLAIR": (CD, "WRITING INSTRUMENTS", "Pens, stationery and writing instruments", MFR, PVT, "PLASTIC / POLYMER", CONS, "PENS|STATIONERY|WRITING", "CONSUMPTION"),
    "KDDL": (CD, "WATCH COMPONENTS & RETAIL", "Watch dials, hands and Ethos luxury watch retail", MFR, PVT, "STEEL | GLASS", CONS_IMP, "WATCH DIALS|ETHOS|LUXURY RETAIL", "CONSUMPTION|LUXURY"),
    "POKARNA": (CB, "QUARTZ & GRANITE", "Engineered quartz surfaces and granite", MFR, PVT, "SILICA SAND | SODA ASH | NATURAL GAS | LIMESTONE", "EXPORT ORIENTED | HOUSING | CONSUMER DRIVEN".replace("HOUSING | ", ""), "QUARTZ|GRANITE|QUANTRA|SURFACES", "BUILDING MATERIALS|EXPORTS"),
    "NITCO": (CB, "TILES", "Ceramic and vitrified tiles and marble", MFR, PVT, "CLAY | FELDSPAR | KAOLIN | BRASS", "HOUSING | CONSUMER DRIVEN | IMPORT DEPENDENT", "TILES|VITRIFIED|MARBLE", "BUILDING MATERIALS|HOUSING"),
    "PRINCEPIPE": (CB, "PLASTIC PIPES", "PVC and CPVC pipes and fittings", MFR, PVT, "PVC RESIN | CRUDE OIL", "HOUSING | CONSUMER DRIVEN | IMPORT DEPENDENT", "PVC PIPES|CPVC|PLUMBING|AGRI", "BUILDING MATERIALS|HOUSING"),
    "INDIANHUME": (CB, "CONCRETE PIPES", "Prestressed concrete pipes and water infrastructure EPC", EPC, PVT, "CEMENT | STEEL", GOVT, "CONCRETE PIPES|WATER|JAL JEEVAN", "INFRASTRUCTURE|WATER"),
    "DDEVPLSTIK": (CH, "POLYMER COMPOUNDS", "Polymer compounds for wire, cable and pipes", MFR, PVT, "PLASTIC / POLYMER", "IMPORT DEPENDENT | GOVERNMENT SPENDING", "POLYMER COMPOUND|XLPE|CABLE", "CHEMICALS|CAPEX"),
    "RESPONIND": (CH, "PVC PRODUCTS", "PVC flooring, leather cloth and synthetic products", MFR, PVT, "PVC | PLASTIC RESIN", "EXPORT ORIENTED | IMPORT DEPENDENT", "PVC|FLOORING|LEATHER CLOTH", "CHEMICALS|EXPORTS"),
    "FINEORG": (CH, "OLEOCHEMICALS", "Oleochemical-based specialty food and polymer additives", MFR, PVT, "PALM OIL | VEGETABLE OIL", "EXPORT ORIENTED | IMPORT DEPENDENT", "OLEOCHEMICALS|ADDITIVES|FOOD EMULSIFIER", "SPECIALTY CHEMICALS|EXPORTS"),

    # ---------------- textiles & apparel ----------------
    "GARFIBRES": (TX, "TECHNICAL TEXTILES", "Synthetic cordage, fishing nets and geosynthetics", MFR, PVT, "PLASTIC / POLYMER", EXP, "TECHNICAL TEXTILES|AQUACULTURE|CORDAGE", "TEXTILES|EXPORTS"),
    "KKCL": (TX, "BRANDED APPAREL", "Killer, Lawman and Easies branded apparel", MFR, PVT, "COTTON", CONS, "KILLER|LAWMAN|DENIM|APPAREL", "CONSUMPTION|APPAREL"),
    "CANTABIL": (TX, "APPAREL RETAIL", "Cantabil branded apparel manufacturing and retail", MFR, PVT, "COTTON", CONS, "APPAREL|RETAIL|CANTABIL", "CONSUMPTION|RETAIL"),
    "LUXIND": (TX, "INNERWEAR", "Innerwear, hosiery and casual wear", MFR, PVT, "COTTON", CONS, "INNERWEAR|HOSIERY|LUX|ONN", "CONSUMPTION|APPAREL"),
    "SANGAMIND": (TX, "YARN & FABRIC", "PV yarn, denim fabric and seamless garments", MFR, PVT, "COTTON | WOOL", CONS_EXP, "PV YARN|DENIM|SEAMLESS", "TEXTILES"),
    "BOMDYEING": (DV, "TEXTILES & REAL ESTATE", "Textiles, polyester staple fibre and Mumbai real estate", MFR, PVT, "COTTON | CRUDE OIL", "HOUSING | CONSUMER DRIVEN | IMPORT DEPENDENT", "TEXTILES|PSF|REAL ESTATE|WADIA", "TEXTILES|REAL ESTATE"),
    "METROBRAND": (CD, "FOOTWEAR RETAIL", "Metro, Mochi and Walkway footwear retail", DIST, PVT, "LEATHER | RUBBER", CONS, "FOOTWEAR|METRO|MOCHI|RETAIL", "CONSUMPTION|RETAIL"),

    # ---------------- real estate & infrastructure ----------------
    "GRINFRA": (IN, "ROAD EPC", "Highway and road EPC and HAM assets", EPC, PVT, "BITUMEN | STEEL | CEMENT", GOVT, "ROADS|HIGHWAY|HAM|NHAI", "INFRASTRUCTURE|ROADS"),
    "JKIL": (IN, "URBAN INFRASTRUCTURE EPC", "Metro, flyover and urban transport EPC", EPC, PVT, "CEMENT | STEEL", GOVT, "METRO|FLYOVER|URBAN INFRA|MUMBAI", "INFRASTRUCTURE|URBAN"),
    "RUSTOMJEE": (RE, "RESIDENTIAL DEVELOPMENT", "Rustomjee residential projects in Mumbai", EPC, PVT, "CEMENT | STEEL", HOUSE, "RESIDENTIAL|MUMBAI|RUSTOMJEE|REDEVELOPMENT", "REAL ESTATE|HOUSING"),
    "KOLTEPATIL": (RE, "RESIDENTIAL DEVELOPMENT", "Residential projects in Pune, Mumbai and Bengaluru", EPC, PVT, "CEMENT | STEEL", HOUSE, "RESIDENTIAL|PUNE|BLACKSTONE", "REAL ESTATE|HOUSING"),
    "AJMERA": (RE, "RESIDENTIAL DEVELOPMENT", "Residential real estate development in Mumbai", EPC, PVT, "CEMENT | STEEL", HOUSE, "RESIDENTIAL|MUMBAI|AJMERA", "REAL ESTATE|HOUSING"),
    "MARATHON": (RE, "RESIDENTIAL DEVELOPMENT", "Residential and commercial development in Mumbai", EPC, PVT, "CEMENT | STEEL", HOUSE, "RESIDENTIAL|MUMBAI|MARATHON", "REAL ESTATE|HOUSING"),

    # ---------------- hospitality, leisure & travel ----------------
    "VENTIVE": (HT, "HOTELS", "Luxury and business hotels across India", SVC, PVT, NONE, CONS, "HOTELS|LUXURY|PANCHSHIL|MARRIOTT", "HOSPITALITY|TOURISM"),
    "BRIGHOTEL": (HT, "HOTELS", "Brigade group hotel assets in south India", SVC, PVT, NONE, CONS, "HOTELS|BRIGADE|BENGALURU", "HOSPITALITY|TOURISM"),
    "EIHAHOTELS": (HT, "HOTELS", "Oberoi and Trident associated hotel properties", SVC, PVT, NONE, CONS, "HOTELS|OBEROI|TRIDENT", "HOSPITALITY|TOURISM"),
    "WONDERLA": (HT, "AMUSEMENT PARKS", "Amusement parks and resorts", SVC, PVT, NONE, CONS, "AMUSEMENT PARK|LEISURE|RESORT", "HOSPITALITY|LEISURE"),
    "IMAGICAA": (HT, "THEME PARKS", "Theme parks, water parks and snow park", SVC, PVT, NONE, CONS, "THEME PARK|WATER PARK|IMAGICAA", "HOSPITALITY|LEISURE"),
    "DELTACORP": (HT, "GAMING & CASINOS", "Casinos, online gaming and hospitality", SVC, PVT, NONE, CONS, "CASINO|GAMING|GOA|HOSPITALITY", "HOSPITALITY|GAMING"),

    # ---------------- logistics ----------------
    "GATEWAY": (LG, "CONTAINER LOGISTICS", "Container freight stations, ICDs and rail logistics", SVC, PVT, "CRUDE OIL (BUNKER FUEL)", "GOVERNMENT SPENDING | EXPORT ORIENTED", "CFS|ICD|RAIL LOGISTICS|EXIM", "LOGISTICS|EXIM"),
    "TCIEXP": (LG, "EXPRESS DISTRIBUTION", "Time-definite express cargo distribution", SVC, PVT, "CRUDE OIL | FUEL", CONS, "EXPRESS|SURFACE CARGO|B2B LOGISTICS", "LOGISTICS"),

    # ---------------- power & utilities ----------------
    "GIPCL": (PU, "POWER GENERATION", "Lignite, gas and solar power generation in Gujarat", POW, PSU, "COAL | NATURAL GAS", GOVT, "LIGNITE|SOLAR|GUJARAT|PSU", "POWER|PSU"),
    "SOLARWORLD": (PU, "SOLAR EPC", "Solar EPC and rooftop solar installations", EPC, PVT, "POLYSILICON | SILVER | ALUMINIUM", GOVT, "SOLAR|EPC|ROOFTOP|RENEWABLE", "SOLAR|RENEWABLE"),
    "GKENERGY": (PU, "SOLAR PUMPS & EPC", "Solar agricultural pumps and solar EPC", EPC, PVT, "POLYSILICON | SILVER | ALUMINIUM", GOVT, "SOLAR PUMP|PM KUSUM|AGRI SOLAR", "SOLAR|RENEWABLE"),
    "BFUTILITIE": (IN, "INFRASTRUCTURE HOLDING", "Wind power and road infrastructure holdings", POW, PVT, NONE, GOVT, "WIND|ROADS|KALYANI|HOLDING", "INFRASTRUCTURE|RENEWABLE"),

    # ---------------- financial services ----------------
    "UGROCAP": (FS, "MSME LENDING", "Technology-led MSME and small business lending", NBFC, PVT, NONE, RATE, "MSME|NBFC|SME LENDING|CO-LENDING", "LENDING|MSME"),
    "REPCOHOME": (FS, "HOUSING FINANCE", "Home loans to the self-employed and non-salaried", NBFC, PVT, NONE, HOUSE, "HOUSING FINANCE|HFC|SELF EMPLOYED", "LENDING|HOUSING"),
    "JSWHL": (FS, "INVESTMENT HOLDING", "Core investment company holding JSW group stakes", NBFC, PVT, NONE, RATE, "HOLDING|JSW|CIC|INVESTMENT", "HOLDING"),
    "SUMMITSEC": (FS, "INVESTMENT HOLDING", "Investment holding company of the RPG group", NBFC, PVT, NONE, RATE, "HOLDING|RPG|INVESTMENT", "HOLDING"),
    "KIRLOSIND": (FS, "INVESTMENT HOLDING", "Kirloskar group holding with cement and windmill assets", NBFC, PVT, NONE, RATE, "HOLDING|KIRLOSKAR|CEMENT", "HOLDING"),
    "SYSTMTXC": (FS, "BROKING & ADVISORY", "Institutional broking, wealth and investment banking", "BROKER", PVT, NONE, RATE, "BROKING|WEALTH|INVESTMENT BANKING", "CAPITAL MARKETS"),
    "RPSGVENT": (BS, "DIVERSIFIED SERVICES", "IT services, FMCG and sports under RPSG group", SVC, PVT, NONE, CONS, "FIRSTSOURCE|RPSG|FMCG|SPORTS", "BUSINESS SERVICES|HOLDING"),

    # ---------------- services, IT and media ----------------
    "SIS": (BS, "SECURITY & FACILITY SERVICES", "Manned security, cash logistics and facility management", SVC, PVT, NONE, CONS, "SECURITY|FACILITY MANAGEMENT|CASH LOGISTICS", "BUSINESS SERVICES"),
    "HGS": (BS, "BUSINESS PROCESS SERVICES", "Customer experience BPM and digital media services", SVC, PVT, NONE, EXP, "BPM|BPO|CUSTOMER EXPERIENCE|HINDUJA", "BUSINESS SERVICES|EXPORTS"),
    "E2E": (IT, "CLOUD INFRASTRUCTURE", "GPU cloud and infrastructure-as-a-service", PLAT, PVT, "SEMICONDUCTORS / ELECTRONIC COMPONENTS", IMP, "GPU CLOUD|AI|DATACENTRE|IAAS", "AI|DIGITAL"),
    "NPST": (IT, "PAYMENT TECHNOLOGY", "UPI switch and payment technology for banks", PLAT, PVT, NONE, CONS, "UPI|PAYMENTS|FINTECH|SWITCH", "FINTECH|DIGITAL"),
    "DBCORP": (ME, "PRINT MEDIA", "Dainik Bhaskar newspapers, radio and digital", SVC, PVT, "WOOD PULP | WASTEPAPER", CONS, "NEWSPAPER|DAINIK BHASKAR|RADIO|PRINT", "MEDIA"),
}


def main():
    rows = list(csv.DictReader(open(MASTER, encoding="utf-8", errors="ignore")))
    columns = list(rows[0].keys())
    cols = ["SECTOR", "INDUSTRY", "CORE BUSINESS", "BUSINESS_TYPE",
            "OWNERSHIP", "COMMODITY_EXPOSURE", "ECONOMIC_SENSITIVITY",
            "KEYWORDS", "THEMES"]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy(MASTER, f"{MASTER}.{stamp}.bak")

    batch = {r["SYMBOL"].strip().upper() for r in rows
             if STAMP in (r.get("SUBSCRIBE_REASON") or "")}
    filled, switched, left = 0, 0, []
    for row in rows:
        symbol = row["SYMBOL"].strip().upper()
        if symbol not in batch:
            continue
        values = C.get(symbol)
        if not values:
            left.append(symbol)
            row["SUBSCRIBE"] = "NO"
            row["SUBSCRIBE_REASON"] = ("passes the price and mcap rules but I "
                                       "could not identify the company with "
                                       "confidence -- needs manual "
                                       f"classification. {STAMP}")
            continue
        for column, value in zip(cols, values):
            row[column] = value
        filled += 1
        row["SUBSCRIBE"] = "YES"
        row["SUBSCRIBE_REASON"] = (
            (row["SUBSCRIBE_REASON"] or "").split(" -- HELD OFF")[0]
            + f". classified into the existing vocabulary. {STAMP}")
        switched += 1

    with open(MASTER, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    known = sum(1 for r in rows if (r.get("SECTOR") or "").strip())
    watched = sum(1 for r in rows
                  if (r.get("SUBSCRIBE") or "").strip().upper() == "YES")
    print(f"  backed up      master_stocks.csv.{stamp}.bak")
    print(f"  classified     {filled}")
    print(f"  switched ON    {switched}")
    print(f"  SECTOR known   {known} of {len(rows)} "
          f"({known / len(rows) * 100:.1f}%)")
    print(f"  watch list     {watched}")
    if left:
        print(f"\n  left blank on purpose ({len(left)}): {', '.join(sorted(left))}")

    try:
        sys.path.insert(0, ".")
        from core.master_loader import MasterLoader
        loader = MasterLoader()
        loader.load()
        print(f"\n  master_loader OK -- {len(loader.all_symbols())} subscribed")
    except Exception as exc:                                   # noqa: BLE001
        print(f"\n  ! master_loader REFUSED: {str(exc)[:220]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
