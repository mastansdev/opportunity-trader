"""
==========================================================
py tools/classify_batch_aug8b.py  --  the no-data batch
==========================================================

    "take the names of the stocks and research them in online like u
     did last time. all data in that sheet is prepared by you in the
     same method."
                                -- operator, 8 August 2026

WHAT THIS BATCH IS
------------------
65 rows carried no CMP and no market cap, so eligibility could not be
judged and they sat blocked with nothing said about what they even
are. They are not obscure: ALLCARGO GLOBAL, GOODYEAR INDIA, ELANTAS
BECK, RELIANCE INFRASTRUCTURE, SUBEX, KOVAI MEDICAL.

Same method as tools/classify_new_listings.py (July) and
tools/classify_batch_aug8.py (this morning): the existing 29-value
SECTOR vocabulary, one company at a time, and anything I cannot
identify with confidence is DELIBERATELY absent.

CLASSIFYING IS NOT SUBSCRIBING
------------------------------
Every row here stays SUBSCRIBE = NO. They have no price and no market
cap on file, so his two hard rules -- Rs 50 and Rs 2,000 Cr -- cannot
be tested, and a stock that cannot be tested is not eligible.

    "I DON'T WANT JUNK IN MY BOT."

What this fixes is the OTHER half: the bot now knows what these
companies are, so a sector event reaches them and a card about them
lands in the right group the moment prices do arrive.

FIVE REITs AND InvITs ARE REFUSED, NOT CLASSIFIED
-------------------------------------------------
EMBASSY, MINDSPACE, NEXUS SELECT, INDIGRID, CUBE HIGHWAYS and
KNOWLEDGE REALTY are trusts, not companies. tools/complete_master.py
already refuses them by pattern; giving one a business sector would
put a property basket inside the sector-strength gate as though it
were a stock.

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

AU, BS, CG, CB, CH = ("AUTOMOBILE", "BUSINESS SERVICES", "CAPITAL GOODS",
                      "CEMENT & BUILDING MATERIALS", "CHEMICALS")
CD, CDU, DV, FS = ("CONSUMER DISCRETIONARY", "CONSUMER DURABLES",
                   "DIVERSIFIED", "FINANCIAL SERVICES")
FM, HS, HT, IT = ("FMCG", "HEALTHCARE SERVICES", "HOSPITALITY & TOURISM",
                  "INFORMATION TECHNOLOGY")
IN, LG, MM = "INFRASTRUCTURE", "LOGISTICS & TRANSPORTATION", "METALS & MINING"
PH, PU, RE, TX = ("PHARMACEUTICALS", "POWER & UTILITIES", "REAL ESTATE",
                  "TEXTILES & APPAREL")
AG = "AGRICULTURE & FERTILIZERS"
TE = "TELECOM"

MFR, SVC, EPC = "MANUFACTURER", "SERVICE PROVIDER", "EPC / CONTRACTOR"
NBFC, DIST, PLAT, POW = "NBFC", "DISTRIBUTOR", "PLATFORM", "POWER GENERATOR"
PVT, MNC, PSU = "PRIVATE", "MNC", "PSU"
NONE = "NONE"
CONS, EXP, IMP = "CONSUMER DRIVEN", "EXPORT ORIENTED", "IMPORT DEPENDENT"
GOVT, RATE = "GOVERNMENT SPENDING", "INTEREST RATE SENSITIVE"
HOUSE = "INTEREST RATE SENSITIVE | HOUSING"
CONS_EXP = "CONSUMER DRIVEN | EXPORT ORIENTED"
CONS_IMP = "CONSUMER DRIVEN | IMPORT DEPENDENT"
GOVT_EXP = "GOVERNMENT SPENDING | EXPORT ORIENTED"
EXP_IMP = "EXPORT ORIENTED | IMPORT DEPENDENT"

C = {
    # ---------------- chemicals ----------------
    "BODALCHEM": (CH, "DYES & INTERMEDIATES", "Dyestuffs, dye intermediates and basic chemicals", MFR, PVT, "CRUDE OIL (CHEMICAL INTERMEDIATES)", EXP_IMP, "DYES|INTERMEDIATES|TEXTILE CHEMICALS", "CHEMICALS|EXPORTS"),
    "SUDARCOLOR": (CH, "PIGMENTS", "Organic and inorganic colour pigments", MFR, PVT, "CRUDE OIL DERIVATIVES | TITANIUM DIOXIDE", EXP_IMP, "PIGMENTS|COLOURANTS|SUDARSHAN", "SPECIALTY CHEMICALS"),
    "ULTRAMAR": (CH, "PIGMENTS & SURFACTANTS", "Ultramarine blue pigment and surfactants", MFR, PVT, "CRUDE OIL DERIVATIVES | TITANIUM DIOXIDE", EXP, "PIGMENTS|SURFACTANTS|ULTRAMARINE", "SPECIALTY CHEMICALS"),
    "TRANSPEK": (CH, "SPECIALTY CHEMICALS", "Acid chlorides and specialty organic chemicals", MFR, PVT, "CRUDE OIL (CHEMICAL INTERMEDIATES)", EXP, "ACID CHLORIDE|SPECIALTY|CUSTOM SYNTHESIS", "SPECIALTY CHEMICALS|EXPORTS"),
    "SADHNANIQ": (CH, "SPECIALTY CHEMICALS", "Specialty chemicals and pharma intermediates", MFR, PVT, "CRUDE OIL (CHEMICAL INTERMEDIATES)", EXP, "SPECIALTY|INTERMEDIATES|NITRO", "SPECIALTY CHEMICALS"),
    "ELANTAS": (CH, "ELECTRICAL INSULATION", "Insulating varnishes and electrical resins", MFR, MNC, "CRUDE OIL DERIVATIVES (PLASTICS)", "GOVERNMENT SPENDING | IMPORT DEPENDENT", "INSULATION|RESINS|ALTANA|MNC", "SPECIALTY CHEMICALS|POWER"),
    "GRAUWEIL": (CH, "SURFACE FINISHING", "Electroplating chemicals, paints and lubricants", MFR, PVT, "CRUDE OIL DERIVATIVES (PLASTICS)", "CONSUMER DRIVEN | IMPORT DEPENDENT", "ELECTROPLATING|SURFACE FINISHING|GROWEL", "SPECIALTY CHEMICALS"),
    "PASUPTAC": (CH, "ACRYLIC FIBRE", "Acrylic staple fibre and tow", MFR, PVT, "CRUDE OIL (CHEMICAL INTERMEDIATES)", IMP, "ACRYLIC FIBRE|TEXTILE|ACRYLONITRILE", "CHEMICALS|TEXTILES"),
    "SHIVALIK": (CH, "AGROCHEMICAL TECHNICALS", "Agrochemical technicals and pharma intermediates", MFR, PVT, "AGROCHEMICAL TECHNICALS (PETROCHEMICAL-DERIVED)", EXP, "AGROCHEMICAL|TECHNICALS|API", "AGROCHEM|PHARMA"),

    # ---------------- pharmaceuticals & healthcare ----------------
    "KOPRAN": (PH, "API & FORMULATIONS", "Antibiotic APIs and finished formulations", MFR, PVT, NONE, EXP, "API|ANTIBIOTIC|SARTANS|FORMULATIONS", "PHARMA|API"),
    "ZIMLAB": (PH, "FORMULATIONS", "Oral solid and novel drug delivery formulations", MFR, PVT, NONE, EXP, "FORMULATIONS|NDDS|EMERGING MARKETS", "PHARMA|EXPORTS"),
    "AMANTA": (PH, "STERILE FORMULATIONS", "Blow-fill-seal sterile liquid formulations", MFR, PVT, NONE, EXP, "BFS|STERILE|INJECTABLE|OPHTHALMIC", "PHARMA|INJECTABLES"),
    "KOVAI": (HS, "HOSPITALS", "Multi-speciality hospital chain in Coimbatore", SVC, PVT, NONE, CONS, "HOSPITAL|COIMBATORE|MULTISPECIALITY", "HEALTHCARE"),
    "HEALTHX": (HS, "HEALTHCARE PLATFORM", "Digital healthcare services platform", PLAT, PVT, NONE, CONS, "HEALTHTECH|DIGITAL HEALTH|PLATFORM", "HEALTHCARE|DIGITAL"),

    # ---------------- capital goods & engineering ----------------
    "COCKERILL": (CG, "HEAVY ENGINEERING", "Industrial furnaces, boilers and defence equipment", MFR, MNC, "STEEL", GOVT_EXP, "FURNACES|BOILERS|DEFENCE|JOHN COCKERILL", "CAPEX|DEFENCE"),
    "KLBRENG-B": (CG, "PROCESS EQUIPMENT", "Industrial dryers and process equipment", MFR, PVT, "STEEL", GOVT, "DRYERS|PROCESS EQUIPMENT|DEFENCE", "CAPEX|ENGINEERING"),
    "SIKA": (CG, "PRECISION ENGINEERING", "Aerospace and defence precision components", MFR, PVT, "TITANIUM | NICKEL ALLOYS", GOVT, "AEROSPACE|DEFENCE|PRECISION", "DEFENCE|CAPEX"),
    "SWANDEF": (CG, "SHIPBUILDING & DEFENCE", "Shipbuilding, repair and heavy defence engineering", MFR, PVT, "STEEL", GOVT, "SHIPYARD|DEFENCE|PIPAVAV|SHIPBUILDING", "DEFENCE|CAPEX"),
    "FRONTSP": (CG, "RAILWAY COMPONENTS", "Springs and forgings for railways and automotive", MFR, PVT, "STEEL", GOVT, "SPRINGS|RAILWAYS|FORGINGS", "RAILWAYS|CAPEX"),
    "SETL": (CG, "ENGINEERING SERVICES", "Standard engineering products and technology services", MFR, PVT, "STEEL", GOVT, "ENGINEERING|FABRICATION", "ENGINEERING"),
    "TAALTECH": (IT, "ENGINEERING SERVICES", "Outsourced engineering design and R&D services", SVC, PVT, NONE, EXP, "ENGINEERING SERVICES|ER&D|DESIGN", "IT SERVICES|EXPORTS"),
    "VIVIANA": (PU, "SOLAR EPC", "Solar EPC and industrial electrical contracting", EPC, PVT, "POLYSILICON | SILVER | ALUMINIUM", GOVT, "SOLAR|EPC|ELECTRICAL", "SOLAR|RENEWABLE"),
    "INA": (PU, "SOLAR MODULES", "Solar photovoltaic module manufacturing", MFR, PVT, "POLYSILICON | SILVER | ALUMINIUM", GOVT, "SOLAR MODULES|PV|INSOLATION", "SOLAR|RENEWABLE"),
    "KOTYARK": (CH, "BIODIESEL", "Biodiesel and renewable fuel manufacturing", MFR, PVT, "PALM OIL | VEGETABLE OIL", GOVT, "BIODIESEL|RENEWABLE FUEL|ETHANOL", "RENEWABLE|ENERGY"),

    # ---------------- auto & components ----------------
    "GOODYEAR": (AU, "TYRES", "Farm and passenger vehicle tyres", MFR, MNC, "NATURAL RUBBER | CARBON BLACK | CRUDE OIL", CONS, "TYRES|FARM|GOODYEAR|MNC", "AUTO ANCILLARY|AGRI"),
    "STERTOOLS": (AU, "AUTO COMPONENTS", "Fasteners and cold-forged auto components", MFR, PVT, "STEEL", CONS, "FASTENERS|COLD FORGING|AUTO", "AUTO ANCILLARY"),
    "HITECHGEAR": (AU, "AUTO COMPONENTS", "Transmission gears and shafts for commercial vehicles", MFR, PVT, "STEEL", CONS_EXP, "GEARS|TRANSMISSION|CV", "AUTO ANCILLARY"),
    "PRADPME": (MM, "STEEL FORGINGS", "Stainless and alloy steel forged components", MFR, PVT, "STEEL | NICKEL | CHROMIUM | MOLYBDENUM", EXP, "FORGINGS|STAINLESS|OIL AND GAS", "METALS|EXPORTS"),
    "NILE": (MM, "LEAD RECYCLING", "Lead and lead alloys from recycled batteries", MFR, PVT, "LEAD", "EXPORT ORIENTED | IMPORT DEPENDENT", "LEAD|RECYCLING|BATTERY", "METALS|RECYCLING"),
    "WELSPLSOL": (MM, "SPECIALTY STEEL", "Stainless steel bars, wire rods and seamless tubes", MFR, PVT, "STEEL|NICKEL", GOVT_EXP, "STAINLESS|SEAMLESS|WELSPUN", "METALS"),

    # ---------------- infrastructure, realty, logistics ----------------
    "AGL": (LG, "MULTIMODAL LOGISTICS", "Container freight, contract logistics and express", SVC, PVT, "CRUDE OIL | FUEL", "GOVERNMENT SPENDING | EXPORT ORIENTED", "CFS|LOGISTICS|ALLCARGO|EXIM", "LOGISTICS|EXIM"),
    "PATINTLOG": (LG, "FREIGHT FORWARDING", "Air and surface freight forwarding and courier", SVC, PVT, "CRUDE OIL | FUEL", CONS, "FREIGHT FORWARDING|COURIER|LOGISTICS", "LOGISTICS"),
    "NOIDATOLL": (IN, "TOLL INFRASTRUCTURE", "Delhi-Noida toll bridge concession", SVC, PVT, NONE, GOVT, "TOLL|BRIDGE|CONCESSION|NOIDA", "INFRASTRUCTURE"),
    "BCPL": (IN, "RAILWAY INFRASTRUCTURE", "Railway electrification and civil infrastructure EPC", EPC, PVT, "CEMENT | STEEL", GOVT, "RAILWAY|ELECTRIFICATION|EPC", "INFRASTRUCTURE|RAILWAYS"),
    "NIRAJ": (CB, "CONCRETE & CIVIL", "Ready-mix concrete and civil construction", EPC, PVT, "CEMENT | STEEL", GOVT, "RMC|CIVIL|CONCRETE", "INFRASTRUCTURE"),
    "REPL": (IN, "URBAN PLANNING & PMC", "Urban planning, project management and consultancy", SVC, PVT, NONE, GOVT, "URBAN PLANNING|PMC|SMART CITY", "INFRASTRUCTURE|CONSULTING"),
    "RELINFRA": (IN, "POWER & INFRASTRUCTURE", "Power distribution, EPC, roads and defence", EPC, PVT, "CEMENT | STEEL", GOVT, "POWER DISTRIBUTION|EPC|ROADS|DEFENCE", "INFRASTRUCTURE|POWER"),

    # ---------------- consumer, textiles, agri ----------------
    "ONIDA": (CDU, "CONSUMER ELECTRONICS", "Televisions, washing machines and home appliances", MFR, PVT, "STEEL | ALUMINUM | PLASTICS", CONS_IMP, "TELEVISION|APPLIANCES|ONIDA|MIRC", "CONSUMPTION"),
    "PREMCO": (TX, "NARROW FABRICS", "Woven elastic tapes and narrow fabrics for apparel", MFR, PVT, "COTTON", CONS_EXP, "ELASTIC|NARROW FABRIC|INNERWEAR", "TEXTILES"),
    "RSWM": (TX, "YARN & FABRIC", "Synthetic and blended yarn, denim and fabric", MFR, PVT, "COTTON | WOOL", CONS_EXP, "YARN|DENIM|LNJ BHILWARA", "TEXTILES"),
    "ALPINETEX": (TX, "TEXTILE TRADING", "Textile trading and fabric distribution", DIST, PVT, "COTTON", CONS, "TEXTILE|FABRIC|TRADING", "TEXTILES"),
    "MAFATIND": (TX, "TEXTILES & REALTY", "Textiles, chemicals and land development", MFR, PVT, "COTTON", CONS, "TEXTILES|MAFATLAL|LAND", "TEXTILES|REAL ESTATE"),
    "SHINDL": (FM, "AQUACULTURE", "Shrimp hatchery, farming and seafood processing", MFR, PVT, "FISH MEAL | SOYBEAN MEAL | WHEAT", EXP, "SHRIMP|AQUACULTURE|SEAFOOD|EXPORTS", "AGRI|EXPORTS"),
    "BSHSL": (AG, "SEEDS", "Hybrid cotton and vegetable seeds", MFR, PVT, "MAIZE | COTTON", CONS, "SEEDS|HYBRID|COTTON|AGRI", "AGRI"),
    "COFFEEDAY": (CD, "CAFE CHAIN", "Cafe Coffee Day retail chain and coffee estates", SVC, PVT, "COFFEE", CONS, "CAFE|COFFEE|CCD|RETAIL", "CONSUMPTION"),
    "SAYAJIHOTL": (HT, "HOTELS", "Hotels and restaurant operations", SVC, PVT, NONE, CONS, "HOTELS|RESTAURANTS|SAYAJI|BARBEQUE", "HOSPITALITY|TOURISM"),
    "PREMIER": (CD, "AUTO & ENGINEERING", "Automotive and engineering products", MFR, PVT, "STEEL", CONS, "AUTOMOBILE|ENGINEERING|PREMIER", "AUTO ANCILLARY"),

    # ---------------- technology, media, services ----------------
    "SUBEXLTD": (IT, "TELECOM SOFTWARE", "Revenue assurance and fraud analytics for telecom", PLAT, PVT, NONE, EXP, "TELECOM SOFTWARE|FRAUD|ANALYTICS|SAAS", "IT SERVICES|EXPORTS"),
    "DIGISPICE": (TE, "DIGITAL & FINTECH SERVICES", "Digital technology services and rural fintech", PLAT, PVT, NONE, CONS, "FINTECH|DIGITAL|SPICE MONEY|RURAL", "FINTECH|DIGITAL"),
    "APTECHT": (BS, "EDUCATION & TRAINING", "Vocational IT, media and animation training", SVC, PVT, NONE, CONS, "EDUCATION|TRAINING|APTECH|FRANCHISE", "EDUCATION"),
    "CLEDUCATE": (BS, "EDUCATION & TESTING", "Test preparation, publishing and education services", SVC, PVT, NONE, CONS, "EDUCATION|TEST PREP|CAREER LAUNCHER", "EDUCATION"),
    "ELITECON": (CD, "TRADING & DISTRIBUTION", "Trading and distribution of consumer goods", DIST, PVT, NONE, CONS, "TRADING|DISTRIBUTION|AGRI PRODUCTS", "CONSUMPTION"),

    # ---------------- holding & investment ----------------
    "INDPRUD": (FS, "INVESTMENT HOLDING", "Investment holding company", NBFC, PVT, NONE, RATE, "HOLDING|INVESTMENT|PORTFOLIO", "HOLDING"),
    "WELINV": (FS, "INVESTMENT HOLDING", "Welspun group investment holding company", NBFC, PVT, NONE, RATE, "HOLDING|WELSPUN|INVESTMENT", "HOLDING"),
}


def main():
    rows = list(csv.DictReader(open(MASTER, encoding="utf-8", errors="ignore")))
    columns = list(rows[0].keys())
    cols = ["SECTOR", "INDUSTRY", "CORE BUSINESS", "BUSINESS_TYPE",
            "OWNERSHIP", "COMMODITY_EXPOSURE", "ECONOMIC_SENSITIVITY",
            "KEYWORDS", "THEMES"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy(MASTER, f"{MASTER}.{stamp}.bak")

    filled, left = 0, []
    for row in rows:
        symbol = row["SYMBOL"].strip().upper()
        if str(row.get("SECTOR") or "").strip():
            continue
        if "no CMP or market cap on file" not in row["SUBSCRIBE_REASON"]:
            continue
        values = C.get(symbol)
        if not values:
            left.append(symbol)
            continue
        for column, value in zip(cols, values):
            row[column] = value
        # ---- CLASSIFIED IS NOT SUBSCRIBED ----
        # No price and no market cap means his two hard rules cannot be
        # tested, and an untested stock is not eligible.
        row["SUBSCRIBE"] = "NO"
        row["SUBSCRIBE_REASON"] = (
            f"classified, but no CMP or market cap on file so the Rs 50 and "
            f"Rs 2,000 Cr rules cannot be tested -- stays out until prices "
            f"arrive. {STAMP}")
        filled += 1

    with open(MASTER, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    known = sum(1 for r in rows if (r.get("SECTOR") or "").strip())
    print(f"  backed up      master_stocks.csv.{stamp}.bak")
    print(f"  classified     {filled}")
    print(f"  SECTOR known   {known} of {len(rows)} "
          f"({known / len(rows) * 100:.1f}%)")
    if left:
        print(f"\n  not classified ({len(left)}) -- trusts, or a ticker with "
              f"no company name:\n    {', '.join(sorted(left))}")
    try:
        sys.path.insert(0, ".")
        from core.master_loader import MasterLoader
        loader = MasterLoader()
        loader.load()
        print(f"\n  master_loader OK -- {len(loader.all_symbols())} subscribed")
    except Exception as exc:                                   # noqa: BLE001
        print(f"\n  ! master_loader REFUSED: {str(exc)[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
