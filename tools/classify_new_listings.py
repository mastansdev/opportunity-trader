"""
Classify the new listings tools/morning_universe.py queued into the
master with identity only.

Every value below uses the EXISTING column vocabulary already in
data/master_stocks.csv (29 SECTOR values, 12 BUSINESS_TYPE, 3
OWNERSHIP) so the sector-strength gate keeps grouping these with their
real peers instead of inventing a one-stock sector.

Symbols I could not identify with confidence are DELIBERATELY not in
this table. They stay SUBSCRIBE=NO with an honest reason. A guessed
sector is worse than a blocked stock: it silently mis-groups the name
inside the top-8 sector gate and nothing ever tells you.

Order: SECTOR, INDUSTRY, CORE BUSINESS, BUSINESS_TYPE, OWNERSHIP,
       COMMODITY_EXPOSURE, ECONOMIC_SENSITIVITY, KEYWORDS, THEMES
"""

import sys

import pandas as pd

MASTER = "data/master_stocks.csv"

PH = "PHARMACEUTICALS"
CH = "CHEMICALS"
CG = "CAPITAL GOODS"
AU = "AUTOMOBILE"
MM = "METALS & MINING"
IT = "INFORMATION TECHNOLOGY"
FS = "FINANCIAL SERVICES"
FM = "FMCG"
CD = "CONSUMER DISCRETIONARY"
CDU = "CONSUMER DURABLES"
TX = "TEXTILES & APPAREL"
PP = "PAPER & PACKAGING"
OG = "OIL & GAS"
IN = "INFRASTRUCTURE"
RE = "REAL ESTATE"
LG = "LOGISTICS & TRANSPORTATION"
HC = "HEALTHCARE SERVICES"
PU = "POWER & UTILITIES"
CB = "CEMENT & BUILDING MATERIALS"
AG = "AGRICULTURE & FERTILIZERS"
BS = "BUSINESS SERVICES"
DP = "INTERNET & DIGITAL PLATFORMS"
HT = "HOSPITALITY & TOURISM"
ME = "MEDIA & ENTERTAINMENT"
TE = "TELECOM"

MFG = "MANUFACTURER"
SVC = "SERVICE PROVIDER"
EPC = "EPC / CONTRACTOR"
DIST = "DISTRIBUTOR"
PLAT = "PLATFORM"
NBFC = "NBFC"
BROK = "BROKER"
MINE = "MINING"
POW = "POWER GENERATOR"

PVT, PSU, MNC = "PRIVATE", "PSU", "MNC"
NONE = "NONE"
CONS = "CONSUMER DRIVEN"
GOVT = "GOVERNMENT SPENDING"
EXP = "EXPORT ORIENTED"
IRS = "INTEREST RATE SENSITIVE"
IMP = "IMPORT DEPENDENT"

C = {
    # ---------------- pharma & healthcare ----------------
    "ASTRAZEN": (PH, "PHARMACEUTICALS", "Patented formulations", MFG, MNC, NONE, CONS, "PHARMA|ONCOLOGY|MNC", "PHARMA|MNC"),
    "SANOFI": (PH, "PHARMACEUTICALS", "Branded formulations", MFG, MNC, NONE, CONS, "PHARMA|DIABETES|MNC", "PHARMA|MNC"),
    "NOVARTIND": (PH, "PHARMACEUTICALS", "Branded formulations", MFG, MNC, NONE, CONS, "PHARMA|MNC", "PHARMA|MNC"),
    "SUVEN": (PH, "PHARMACEUTICALS", "CDMO and specialty intermediates", MFG, PVT, NONE, EXP, "PHARMA|CDMO|CRAMS", "PHARMA|CDMO"),
    "SOLARA": (PH, "PHARMACEUTICALS", "Active pharmaceutical ingredients", MFG, PVT, NONE, EXP, "PHARMA|API", "PHARMA|API"),
    "HIKAL": (PH, "PHARMACEUTICALS", "API and crop protection intermediates", MFG, PVT, NONE, EXP, "PHARMA|API|AGROCHEM", "PHARMA|API"),
    "WANBURY": (PH, "PHARMACEUTICALS", "Active pharmaceutical ingredients", MFG, PVT, NONE, EXP, "PHARMA|API", "PHARMA|API"),
    "INDSWFTLAB": (PH, "PHARMACEUTICALS", "Active pharmaceutical ingredients", MFG, PVT, NONE, EXP, "PHARMA|API", "PHARMA|API"),
    "ZOTA": (PH, "PHARMACEUTICALS", "Generic formulations", MFG, PVT, NONE, CONS, "PHARMA|GENERICS", "PHARMA"),
    "FERMENTA": (PH, "PHARMACEUTICALS", "Vitamin D3 and biotech APIs", MFG, PVT, NONE, EXP, "PHARMA|API|VITAMIN", "PHARMA|API"),
    "INNOVACAP": (PH, "PHARMACEUTICALS", "Contract manufacturing of formulations", MFG, PVT, NONE, CONS, "PHARMA|CDMO", "PHARMA|CDMO"),
    "SENORES": (PH, "PHARMACEUTICALS", "Regulated-market generic formulations", MFG, PVT, NONE, EXP, "PHARMA|GENERICS|US FDA", "PHARMA"),
    "BAJAJHCARE": (PH, "PHARMACEUTICALS", "APIs and formulations", MFG, PVT, NONE, EXP, "PHARMA|API", "PHARMA|API"),
    "KRSNAA": (HC, "DIAGNOSTICS", "Radiology and pathology diagnostics", SVC, PVT, NONE, GOVT, "DIAGNOSTICS|PPP|RADIOLOGY", "HEALTHCARE"),
    "NEPHROPLUS": (HC, "DIALYSIS", "Dialysis clinic network", SVC, PVT, NONE, CONS, "DIALYSIS|CLINICS|NEPHROLOGY", "HEALTHCARE"),
    "VIMTALABS": (HC, "TESTING & CRO", "Contract research and analytical testing", SVC, PVT, NONE, EXP, "CRO|TESTING|LABS", "HEALTHCARE|CRO"),

    # ---------------- chemicals ----------------
    "APCOTEXIND": (CH, "SPECIALTY CHEMICALS", "Synthetic latex and rubber", MFG, PVT, NONE, EXP, "LATEX|RUBBER|SPECIALTY", "SPECIALTY CHEMICALS"),
    "CHEMPLASTS": (CH, "COMMODITY CHEMICALS", "PVC resins and custom manufacturing", MFG, PVT, "CRUDE OIL", IMP, "PVC|CHLOR ALKALI", "CHEMICALS"),
    "EPIGRAL": (CH, "COMMODITY CHEMICALS", "Chlor-alkali and derivatives", MFG, PVT, NONE, IMP, "CHLOR ALKALI|PVC|CPVC", "CHEMICALS"),
    "KIRIINDUS": (CH, "DYES & PIGMENTS", "Dyes and dye intermediates", MFG, PVT, NONE, EXP, "DYES|INTERMEDIATES", "CHEMICALS"),
    "VISHNU": (CH, "SPECIALTY CHEMICALS", "Chromium and barium chemicals", MFG, PVT, NONE, EXP, "CHROME|BARIUM|SPECIALTY", "SPECIALTY CHEMICALS"),
    "TATVA": (CH, "SPECIALTY CHEMICALS", "Structure directing agents and PTC", MFG, PVT, NONE, EXP, "SDA|PTC|SPECIALTY", "SPECIALTY CHEMICALS"),
    "INDOBORAX": (CH, "SPECIALTY CHEMICALS", "Boron chemicals", MFG, PVT, NONE, IMP, "BORON|BORAX", "CHEMICALS"),
    "KINGFA": (CH, "POLYMERS", "Engineered polymer compounds", MFG, MNC, NONE, IMP, "POLYMER|COMPOUNDS", "CHEMICALS"),
    "STALLION": (CH, "SPECIALTY CHEMICALS", "Refrigerant and specialty fluorochemicals", DIST, PVT, NONE, IMP, "FLUOROCHEMICALS|REFRIGERANT", "CHEMICALS"),
    "GSPCROP": (AG, "AGROCHEMICALS", "Crop protection chemicals", MFG, PVT, NONE, CONS, "AGROCHEM|PESTICIDES", "AGRI"),
    "SOTL": (OG, "LUBRICANTS", "Transformer oils and lubricants", MFG, PVT, "CRUDE OIL", IMP, "LUBRICANTS|TRANSFORMER OIL", "OIL & GAS"),

    # ---------------- packaging & paper ----------------
    "COSMOFIRST": (PP, "FLEXIBLE PACKAGING", "BOPP and specialty films", MFG, PVT, "CRUDE OIL", EXP, "BOPP|FILMS|PACKAGING", "PACKAGING"),
    "POLYPLEX": (PP, "FLEXIBLE PACKAGING", "PET and BOPP films", MFG, PVT, "CRUDE OIL", EXP, "PET FILM|PACKAGING", "PACKAGING"),
    "UFLEX": (PP, "FLEXIBLE PACKAGING", "Flexible packaging and films", MFG, PVT, "CRUDE OIL", EXP, "FLEXIBLE PACKAGING|FILMS", "PACKAGING"),
    "MOLDTKPAC": (PP, "RIGID PACKAGING", "Injection moulded rigid packaging", MFG, PVT, "CRUDE OIL", CONS, "RIGID PACKAGING|IML", "PACKAGING"),
    "WSTCSTPAPR": (PP, "PAPER", "Writing printing and packaging paper", MFG, PVT, NONE, CONS, "PAPER|PULP", "PAPER"),

    # ---------------- capital goods ----------------
    "ADOR": (CG, "WELDING", "Welding consumables and equipment", MFG, PVT, "STEEL", GOVT, "WELDING|CONSUMABLES", "CAPEX"),
    "BBL": (CG, "ELECTRICAL EQUIPMENT", "Transformers and electric motors", MFG, PVT, "STEEL|COPPER", GOVT, "TRANSFORMERS|MOTORS", "POWER CAPEX"),
    "HIRECT": (CG, "ELECTRICAL EQUIPMENT", "Power electronics and rectifiers", MFG, PVT, NONE, GOVT, "RECTIFIERS|POWER ELECTRONICS|RAILWAYS", "RAILWAYS|CAPEX"),
    "CONTROLPR": (CG, "INDUSTRIAL PRODUCTS", "Coding and marking systems", MFG, PVT, NONE, CONS, "CODING|MARKING|PRINTING", "CAPEX"),
    "CENTUM": (CG, "ELECTRONICS MANUFACTURING", "Electronic system design and manufacturing", MFG, PVT, NONE, GOVT, "ESDM|DEFENCE|ELECTRONICS", "DEFENCE|ELECTRONICS"),
    "CYIENTDLM": (CG, "ELECTRONICS MANUFACTURING", "Electronics manufacturing services", MFG, PVT, NONE, EXP, "EMS|ESDM|AEROSPACE", "ELECTRONICS|DEFENCE"),
    "SHILCTECH": (CG, "ELECTRICAL EQUIPMENT", "Distribution and power transformers", MFG, PVT, "STEEL|COPPER", GOVT, "TRANSFORMERS|RENEWABLE", "POWER CAPEX"),
    "GENUSPOWER": (CG, "ELECTRICAL EQUIPMENT", "Smart electricity meters", MFG, PVT, NONE, GOVT, "SMART METERS|RDSS", "POWER CAPEX|SMART METERING"),
    "UNIVCABLES": (CG, "CABLES", "Power and telecom cables", MFG, PVT, "COPPER|ALUMINIUM", GOVT, "CABLES|CONDUCTORS", "POWER CAPEX"),
    "DYCL": (CG, "CABLES", "Power cables and conductors", MFG, PVT, "COPPER|ALUMINIUM", GOVT, "CABLES|POWER", "POWER CAPEX"),
    "INGERRAND": (CG, "INDUSTRIAL PRODUCTS", "Air compressors and industrial systems", MFG, MNC, NONE, GOVT, "COMPRESSORS|MNC", "CAPEX|MNC"),
    "WENDT": (CG, "ABRASIVES", "Super abrasives and precision machines", MFG, MNC, NONE, GOVT, "ABRASIVES|PRECISION", "CAPEX"),
    "GRINDWELL": (CG, "ABRASIVES", "Abrasives and ceramics", MFG, MNC, NONE, GOVT, "ABRASIVES|CERAMICS|MNC", "CAPEX|MNC"),
    "WALCHANNAG": (CG, "HEAVY ENGINEERING", "Heavy engineering and defence equipment", MFG, PVT, "STEEL", GOVT, "HEAVY ENGINEERING|DEFENCE|NUCLEAR", "DEFENCE|CAPEX"),
    "WPIL": (CG, "PUMPS", "Engineered pumps and water systems", MFG, PVT, "STEEL", GOVT, "PUMPS|WATER", "WATER|CAPEX"),
    "SANGHVIMOV": (CG, "EQUIPMENT RENTAL", "Heavy crane rental services", SVC, PVT, NONE, GOVT, "CRANES|RENTAL|WIND", "CAPEX|RENEWABLES"),
    "KABRAEXTRU": (CG, "MACHINERY", "Plastic extrusion machinery", MFG, PVT, "STEEL", GOVT, "EXTRUSION|MACHINERY|BATTERY", "CAPEX|EV"),
    "ICEMAKE": (CG, "REFRIGERATION", "Commercial refrigeration equipment", MFG, PVT, "STEEL", CONS, "REFRIGERATION|COLD CHAIN", "COLD CHAIN"),
    "EPACKPEB": (CG, "PRE-ENGINEERED BUILDINGS", "Pre-engineered steel buildings", MFG, PVT, "STEEL", GOVT, "PEB|STEEL BUILDINGS", "CAPEX"),
    "JNKINDIA": (CG, "PROCESS EQUIPMENT", "Fired heaters and process equipment", MFG, PVT, "STEEL", GOVT, "HEATERS|REFINERY|OIL AND GAS", "CAPEX"),
    "PREMEXPLN": (CG, "DEFENCE", "Explosives and defence propellants", MFG, PVT, NONE, GOVT, "EXPLOSIVES|DEFENCE|PROPELLANTS", "DEFENCE"),
    "KRISHNADEF": (CG, "DEFENCE", "Defence and allied engineering components", MFG, PVT, "STEEL", GOVT, "DEFENCE|COMPONENTS", "DEFENCE"),
    "QUADFUTURE": (CG, "RAILWAY EQUIPMENT", "Train control and specialty cables", MFG, PVT, NONE, GOVT, "RAILWAYS|KAVACH|SIGNALLING", "RAILWAYS|DEFENCE"),
    "KERNEX": (CG, "RAILWAY EQUIPMENT", "Railway safety and signalling systems", MFG, PVT, NONE, GOVT, "RAILWAYS|KAVACH|SIGNALLING", "RAILWAYS"),
    "MARINE": (CG, "ELECTRICAL EQUIPMENT", "Marine and industrial electricals", MFG, PVT, NONE, GOVT, "MARINE|ELECTRICALS|DEFENCE", "DEFENCE|CAPEX"),
    "SEDEMAC": (CG, "INDUSTRIAL PRODUCTS", "Mechatronics and control systems", MFG, PVT, NONE, CONS, "MECHATRONICS|CONTROLS|ENGINE", "AUTO ANCILLARY"),
    "ADVAIT": (CG, "POWER TRANSMISSION", "Transmission line hardware and services", MFG, PVT, "ALUMINIUM|STEEL", GOVT, "TRANSMISSION|OPGW|GREEN HYDROGEN", "POWER CAPEX"),
    "HLEGLAS": (CG, "PROCESS EQUIPMENT", "Glass-lined and specialty process equipment", MFG, PVT, "STEEL", GOVT, "GLASS LINED|PHARMA EQUIPMENT", "CAPEX"),
    "CMPDI": (MM, "MINING SERVICES", "Mine planning and design consultancy", SVC, PSU, "COAL", GOVT, "COAL|MINE PLANNING|PSU", "PSU|COAL"),

    # ---------------- auto & ancillaries ----------------
    "ASAL": (AU, "AUTO COMPONENTS", "Sheet metal stampings and assemblies", MFG, PVT, "STEEL", CONS, "STAMPINGS|AUTO ANCILLARY", "AUTO ANCILLARY"),
    "GNA": (AU, "AUTO COMPONENTS", "Axles and driveline components", MFG, PVT, "STEEL", EXP, "AXLES|DRIVELINE|CV", "AUTO ANCILLARY"),
    "SJS": (AU, "AUTO COMPONENTS", "Decorative aesthetics for vehicles", MFG, PVT, NONE, CONS, "AESTHETICS|LOGOS|AUTO ANCILLARY", "AUTO ANCILLARY"),
    "SANDHAR": (AU, "AUTO COMPONENTS", "Locks mirrors and sheet metal parts", MFG, PVT, "STEEL|ALUMINIUM", CONS, "AUTO ANCILLARY|LOCKS", "AUTO ANCILLARY"),
    "LUMAXIND": (AU, "AUTO COMPONENTS", "Automotive lighting systems", MFG, PVT, NONE, CONS, "LIGHTING|AUTO ANCILLARY", "AUTO ANCILLARY"),
    "NRBBEARING": (AU, "AUTO COMPONENTS", "Needle roller bearings", MFG, PVT, "STEEL", CONS, "BEARINGS|AUTO ANCILLARY", "AUTO ANCILLARY"),
    "SUNDRMFAST": (AU, "AUTO COMPONENTS", "Fasteners and precision components", MFG, PVT, "STEEL", EXP, "FASTENERS|AUTO ANCILLARY", "AUTO ANCILLARY"),
    "KROSS": (AU, "AUTO COMPONENTS", "Trailer axles and forged components", MFG, PVT, "STEEL", CONS, "AXLES|FORGINGS|CV", "AUTO ANCILLARY"),
    "UNIPARTS": (AU, "AUTO COMPONENTS", "Precision parts for off-highway equipment", MFG, PVT, "STEEL", EXP, "OFF HIGHWAY|3PL|FORGINGS", "AUTO ANCILLARY"),
    "SSWL": (AU, "AUTO COMPONENTS", "Steel and alloy wheels", MFG, PVT, "STEEL|ALUMINIUM", EXP, "WHEELS|AUTO ANCILLARY", "AUTO ANCILLARY"),
    "NDRAUTO": (AU, "AUTO COMPONENTS", "Automotive seating and components", MFG, PVT, "STEEL", CONS, "SEATING|AUTO ANCILLARY", "AUTO ANCILLARY"),
    "WHEELS": (AU, "AUTO COMPONENTS", "Wheels for commercial and farm vehicles", MFG, PVT, "STEEL", CONS, "WHEELS|AUTO ANCILLARY", "AUTO ANCILLARY"),
    "TINNARUBR": (AU, "AUTO COMPONENTS", "Reclaimed rubber and recycling", MFG, PVT, "RUBBER", CONS, "RECLAIM RUBBER|RECYCLING|TYRE", "RECYCLING"),
    "HARSHA": (AU, "AUTO COMPONENTS", "Precision bearing cages and rings", MFG, PVT, "STEEL", EXP, "BEARING CAGES|PRECISION", "AUTO ANCILLARY"),
    "SPAL": (AU, "AUTO COMPONENTS", "Automotive components", MFG, PVT, "STEEL", CONS, "AUTO ANCILLARY", "AUTO ANCILLARY"),

    # ---------------- metals ----------------
    "GOODLUCK": (MM, "STEEL PRODUCTS", "Steel pipes tubes and structures", MFG, PVT, "STEEL", GOVT, "STEEL PIPES|STRUCTURES|DEFENCE", "CAPEX|DEFENCE"),
    "MANINDS": (MM, "STEEL PRODUCTS", "Large diameter line pipes", MFG, PVT, "STEEL", GOVT, "LINE PIPES|OIL AND GAS|WATER", "CAPEX"),
    "HARIOMPIPE": (MM, "STEEL PRODUCTS", "Steel tubes and pipes", MFG, PVT, "STEEL", GOVT, "STEEL PIPES|TUBES", "CAPEX"),
    "VENUSPIPES": (MM, "STEEL PRODUCTS", "Stainless steel pipes and tubes", MFG, PVT, "STEEL|NICKEL", EXP, "STAINLESS|PIPES|TUBES", "CAPEX"),
    "RAJRATAN": (MM, "STEEL PRODUCTS", "Bead wire for tyres", MFG, PVT, "STEEL", CONS, "BEAD WIRE|TYRE|STEEL WIRE", "AUTO ANCILLARY"),
    "POCL": (MM, "NON-FERROUS", "Lead recycling and metal oxides", MFG, PVT, "LEAD", IMP, "LEAD|RECYCLING|BATTERY", "RECYCLING|EV"),
    "SGMART": (MM, "STEEL TRADING", "Steel and building material distribution", DIST, PVT, "STEEL", GOVT, "STEEL TRADING|DISTRIBUTION", "CAPEX"),

    # ---------------- oil & gas ----------------
    "GANDHAR": (OG, "SPECIALTY OILS", "White oils and petroleum specialities", MFG, PVT, "CRUDE OIL", IMP, "WHITE OIL|SPECIALTY OILS", "OIL & GAS"),
    "SEAMECLTD": (OG, "OILFIELD SERVICES", "Offshore support and diving vessels", SVC, PVT, "CRUDE OIL", GOVT, "OFFSHORE|VESSELS|ONGC", "OIL & GAS"),
    "DEEPINDS": (OG, "OILFIELD SERVICES", "Gas compression and oilfield services", SVC, PVT, "NATURAL GAS", GOVT, "GAS COMPRESSION|ONGC|OILFIELD", "OIL & GAS"),
    "ASIANENE": (OG, "OILFIELD SERVICES", "Seismic and oilfield services", SVC, PVT, "CRUDE OIL", GOVT, "SEISMIC|OILFIELD SERVICES", "OIL & GAS"),
    "JINDRILL": (OG, "OILFIELD SERVICES", "Offshore drilling rigs", SVC, PVT, "CRUDE OIL", GOVT, "DRILLING|OFFSHORE|ONGC", "OIL & GAS"),

    # ---------------- FMCG & agri ----------------
    "BAJAJCON": (FM, "PERSONAL CARE", "Hair oils and personal care", MFG, PVT, NONE, CONS, "HAIR OIL|PERSONAL CARE", "FMCG"),
    "PGHH": (FM, "PERSONAL CARE", "Feminine hygiene and healthcare brands", MFG, MNC, NONE, CONS, "HYGIENE|MNC|FMCG", "FMCG|MNC"),
    "VSTIND": (FM, "TOBACCO", "Cigarettes and leaf tobacco", MFG, PVT, "TOBACCO", CONS, "CIGARETTES|TOBACCO", "FMCG"),
    "GLOBUSSPR": (FM, "BEVERAGES", "Grain spirits and IMFL", MFG, PVT, "GRAIN", CONS, "ALCOHOL|IMFL|ETHANOL", "FMCG|ETHANOL"),
    "PARAGMILK": (FM, "DAIRY", "Milk and value added dairy products", MFG, PVT, "MILK", CONS, "DAIRY|MILK|CHEESE", "FMCG"),
    "SKMEGGPROD": (FM, "PROCESSED FOODS", "Egg powder and processed egg products", MFG, PVT, NONE, EXP, "EGG POWDER|POULTRY", "FMCG"),
    "VENKEYS": (FM, "POULTRY", "Poultry breeding and processed chicken", MFG, PVT, "MAIZE|SOYA", CONS, "POULTRY|BROILER|FEED", "FMCG|AGRI"),
    "ADFFOODS": (FM, "PROCESSED FOODS", "Ethnic packaged foods for export", MFG, PVT, NONE, EXP, "PACKAGED FOOD|ETHNIC|EXPORT", "FMCG"),
    "TRUALT": (AG, "BIOFUEL", "Ethanol and bio-energy", MFG, PVT, "SUGARCANE|GRAIN", GOVT, "ETHANOL|BIOFUEL|BIOGAS", "ETHANOL|RENEWABLES"),
    "GANECOS": (TX, "MAN-MADE FIBRE", "Recycled polyester fibre from PET waste", MFG, PVT, NONE, EXP, "RECYCLED POLYESTER|PET|RPET", "RECYCLING|TEXTILES"),

    # ---------------- textiles & apparel ----------------
    "RAYMOND": (TX, "APPAREL & FABRIC", "Suiting fabric and branded apparel", MFG, PVT, "WOOL|COTTON", CONS, "SUITING|APPAREL|BRANDED", "TEXTILES"),
    "DOLLAR": (TX, "APPAREL", "Branded innerwear and casualwear", MFG, PVT, "COTTON", CONS, "INNERWEAR|HOSIERY|BRANDED", "TEXTILES"),
    "SPORTKING": (TX, "YARN", "Cotton and blended yarn", MFG, PVT, "COTTON", EXP, "YARN|SPINNING|COTTON", "TEXTILES"),
    "MAYURUNIQ": (TX, "SYNTHETIC LEATHER", "PVC and PU synthetic leather", MFG, PVT, "CRUDE OIL", EXP, "SYNTHETIC LEATHER|AUTO UPHOLSTERY", "TEXTILES|AUTO ANCILLARY"),
    "GOCOLORS": (CD, "APPAREL RETAIL", "Women's bottom-wear retail", MFG, PVT, NONE, CONS, "APPAREL RETAIL|WOMENSWEAR", "RETAIL"),

    # ---------------- consumer durables & discretionary ----------------
    "NILKAMAL": (CDU, "PLASTIC PRODUCTS", "Moulded furniture and material handling", MFG, PVT, "CRUDE OIL", CONS, "FURNITURE|CRATES|PLASTICS", "CONSUMER"),
    "STOVEKRAFT": (CDU, "KITCHEN APPLIANCES", "Cookware and kitchen appliances", MFG, PVT, "ALUMINIUM|STEEL", CONS, "COOKWARE|APPLIANCES|PIGEON", "CONSUMER"),
    "CARYSIL": (CDU, "KITCHEN PRODUCTS", "Quartz sinks and kitchen appliances", MFG, PVT, NONE, EXP, "SINKS|QUARTZ|KITCHEN", "CONSUMER"),
    "EPACK": (CDU, "APPLIANCES", "Room air conditioner contract manufacturing", MFG, PVT, "COPPER|ALUMINIUM", CONS, "AC|ODM|CONTRACT MANUFACTURING", "CONSUMER|PLI"),
    "IKIO": (CDU, "LIGHTING", "LED lighting products", MFG, PVT, NONE, CONS, "LED|LIGHTING|ODM", "CONSUMER"),
    "TIMEX": (CD, "WATCHES", "Watches and wearables", MFG, MNC, NONE, CONS, "WATCHES|MNC|BRANDED", "CONSUMER"),
    "LANDMARK": (CD, "AUTO RETAIL", "Premium automotive dealerships", DIST, PVT, NONE, CONS, "AUTO DEALER|SERVICE|PREMIUM", "AUTO RETAIL"),
    "TBZ": (CD, "JEWELLERY", "Branded jewellery retail", MFG, PVT, "GOLD", CONS, "JEWELLERY|GOLD|RETAIL", "JEWELLERY"),
    "GOLDIAM": (CD, "JEWELLERY", "Lab-grown diamond and gold jewellery export", MFG, PVT, "GOLD|DIAMOND", EXP, "JEWELLERY|LAB GROWN|EXPORT", "JEWELLERY"),
    "SHANTIGOLD": (CD, "JEWELLERY", "Gold jewellery manufacturing", MFG, PVT, "GOLD", CONS, "JEWELLERY|GOLD", "JEWELLERY"),
    "DPABHUSHAN": (CD, "JEWELLERY", "Gold and diamond jewellery retail", MFG, PVT, "GOLD", CONS, "JEWELLERY|GOLD|RETAIL", "JEWELLERY"),
    "SHRINGARMS": (CD, "JEWELLERY", "Mangalsutra and gold jewellery", MFG, PVT, "GOLD", CONS, "JEWELLERY|MANGALSUTRA|GOLD", "JEWELLERY"),
    "ASIANHOTNR": (HT, "HOTELS", "Luxury hotel ownership and operation", SVC, PVT, NONE, CONS, "HOTELS|LUXURY|HYATT", "HOSPITALITY"),
    "ITDC": (HT, "TOURISM", "Hotels catering and tourism services", SVC, PSU, NONE, CONS, "TOURISM|HOTELS|PSU", "PSU|HOSPITALITY"),
    "TIPSFILMS": (ME, "FILM PRODUCTION", "Film production and distribution", SVC, PVT, NONE, CONS, "FILMS|CONTENT|BOLLYWOOD", "MEDIA"),

    # ---------------- building materials ----------------
    "GREENLAM": (CB, "LAMINATES", "Decorative laminates and surfaces", MFG, PVT, NONE, CONS, "LAMINATES|SURFACES|PLYWOOD", "HOUSING"),
    "GREENPLY": (CB, "PLYWOOD", "Plywood and MDF panels", MFG, PVT, "TIMBER", CONS, "PLYWOOD|MDF|PANELS", "HOUSING"),
    "STYLAMIND": (CB, "LAMINATES", "Decorative laminates", MFG, PVT, NONE, EXP, "LAMINATES|SURFACES", "HOUSING"),
    "SIRCA": (CB, "PAINTS & COATINGS", "Wood coatings and paints", MFG, PVT, NONE, CONS, "COATINGS|WOOD FINISH|PAINTS", "HOUSING"),
    "MANGLMCEM": (CB, "CEMENT", "Cement manufacturing", MFG, PVT, "LIMESTONE|COAL", GOVT, "CEMENT|CLINKER", "CAPEX|HOUSING"),

    # ---------------- infrastructure & real estate ----------------
    "PSPPROJECT": (IN, "CONSTRUCTION", "Institutional and industrial construction", EPC, PVT, "STEEL|CEMENT", GOVT, "CONSTRUCTION|EPC|BUILDINGS", "CAPEX"),
    "CAPACITE": (IN, "CONSTRUCTION", "High-rise building construction", EPC, PVT, "STEEL|CEMENT", GOVT, "CONSTRUCTION|HIGH RISE|EPC", "CAPEX|HOUSING"),
    "ARSSBL": (IN, "CONSTRUCTION", "Railway and road infrastructure", EPC, PVT, "STEEL|CEMENT", GOVT, "RAILWAYS|ROADS|EPC", "CAPEX"),
    "DENTA": (IN, "WATER INFRASTRUCTURE", "Water management and infrastructure projects", EPC, PVT, "CEMENT", GOVT, "WATER|EPC|IRRIGATION", "WATER|CAPEX"),
    "DREDGECORP": (IN, "DREDGING", "Port and maritime dredging", SVC, PSU, NONE, GOVT, "DREDGING|PORTS|PSU", "PSU|PORTS"),
    "RIIL": (IN, "INDUSTRIAL INFRASTRUCTURE", "Pipeline transport and industrial infrastructure", SVC, PVT, NONE, GOVT, "PIPELINE|INFRASTRUCTURE|RELIANCE", "INFRASTRUCTURE"),
    "ARVSMART": (RE, "REAL ESTATE", "Residential and plotted development", SVC, PVT, "CEMENT|STEEL", IRS, "REAL ESTATE|RESIDENTIAL|AHMEDABAD", "HOUSING"),
    "MAHLIFE": (RE, "REAL ESTATE", "Residential and integrated cities", SVC, PVT, "CEMENT|STEEL", IRS, "REAL ESTATE|RESIDENTIAL|MAHINDRA", "HOUSING"),
    "RAYMONDREL": (RE, "REAL ESTATE", "Residential real estate development", SVC, PVT, "CEMENT|STEEL", IRS, "REAL ESTATE|RESIDENTIAL|THANE", "HOUSING"),

    # ---------------- power & utilities ----------------
    "CLEANMAX": (PU, "RENEWABLE ENERGY", "Captive solar and wind power for industry", POW, PVT, NONE, GOVT, "SOLAR|WIND|C AND I|RENEWABLE", "RENEWABLES"),

    # ---------------- logistics ----------------
    "VRLLOG": (LG, "SURFACE TRANSPORT", "Less-than-truckload goods transport", SVC, PVT, "CRUDE OIL", CONS, "LTL|TRUCKING|PARCEL", "LOGISTICS"),
    "MAHLOG": (LG, "THIRD PARTY LOGISTICS", "Integrated 3PL and mobility services", SVC, PVT, "CRUDE OIL", CONS, "3PL|WAREHOUSING|MAHINDRA", "LOGISTICS"),
    "RITCO": (LG, "SURFACE TRANSPORT", "Full truckload and 3PL services", SVC, PVT, "CRUDE OIL", CONS, "FTL|TRUCKING|3PL", "LOGISTICS"),
    "SHADOWFAX": (LG, "EXPRESS DELIVERY", "Last-mile and quick commerce delivery", PLAT, PVT, NONE, CONS, "LAST MILE|QUICK COMMERCE|GIG", "LOGISTICS|QUICK COMMERCE"),

    # ---------------- financials ----------------
    "ICRA": (FS, "RATING AGENCY", "Credit ratings and analytics", SVC, PVT, NONE, IRS, "RATINGS|ANALYTICS|MOODYS", "FINANCIALS"),
    "CARERATING": (FS, "RATING AGENCY", "Credit ratings and research", SVC, PVT, NONE, IRS, "RATINGS|RESEARCH", "FINANCIALS"),
    "ARMANFIN": (FS, "MICROFINANCE", "Microfinance and two-wheeler lending", NBFC, PVT, NONE, IRS, "MICROFINANCE|MFI|RURAL", "MICROFINANCE"),
    "MUTHOOTMF": (FS, "MICROFINANCE", "Group-lending microfinance", NBFC, PVT, NONE, IRS, "MICROFINANCE|MFI|RURAL", "MICROFINANCE"),
    "SPANDANA": (FS, "MICROFINANCE", "Rural microfinance lending", NBFC, PVT, NONE, IRS, "MICROFINANCE|MFI|RURAL", "MICROFINANCE"),
    "FUSION": (FS, "MICROFINANCE", "Rural microfinance lending", NBFC, PVT, NONE, IRS, "MICROFINANCE|MFI|RURAL", "MICROFINANCE"),
    "SATIN": (FS, "MICROFINANCE", "Microfinance and MSME lending", NBFC, PVT, NONE, IRS, "MICROFINANCE|MFI|MSME", "MICROFINANCE"),
    "NORTHARC": (FS, "DIVERSIFIED NBFC", "Debt financing for under-served sectors", NBFC, PVT, NONE, IRS, "NBFC|DEBT|MSME", "FINANCIALS"),
    "KISSHT": (FS, "DIGITAL LENDING", "Digital consumer and MSME lending", NBFC, PVT, NONE, IRS, "DIGITAL LENDING|FINTECH|BNPL", "FINTECH"),
    "SGFIN": (FS, "SUPPLY CHAIN FINANCE", "Supply chain and channel financing", NBFC, PVT, NONE, IRS, "SUPPLY CHAIN FINANCE|NBFC", "FINANCIALS"),
    "INDOTHAI": (FS, "BROKING", "Stockbroking and financial services", BROK, PVT, NONE, IRS, "BROKING|CAPITAL MARKETS", "CAPITAL MARKETS"),

    # ---------------- IT & platforms ----------------
    "EMUDHRA": (IT, "DIGITAL TRUST", "Digital signatures and identity services", SVC, PVT, NONE, EXP, "DIGITAL SIGNATURE|PKI|CYBERSECURITY", "DIGITAL"),
    "MOSCHIP": (IT, "SEMICONDUCTOR DESIGN", "Semiconductor and embedded design services", SVC, PVT, NONE, EXP, "SEMICONDUCTOR|VLSI|ESDM", "SEMICONDUCTOR"),
    "MPSLTD": (IT, "PUBLISHING SERVICES", "Content and platform services for publishers", SVC, PVT, NONE, EXP, "PUBLISHING|CONTENT|PLATFORM", "IT SERVICES"),
    "PDSL": (TX, "APPAREL SOURCING", "Design and sourcing for global fashion brands", SVC, PVT, "COTTON", EXP, "SOURCING|APPAREL|SUPPLY CHAIN", "TEXTILES"),
    "63MOONS": (IT, "FINANCIAL TECHNOLOGY", "Trading and exchange technology platforms", SVC, PVT, NONE, IRS, "FINTECH|TRADING PLATFORM|EXCHANGE", "FINTECH"),
    "PROTEAN": (IT, "E-GOVERNANCE", "Digital public infrastructure services", SVC, PVT, NONE, GOVT, "EGOV|NPS|DIGITAL INDIA|ONDC", "DIGITAL|GOVTECH"),
    "AMAGI": (IT, "MEDIA TECHNOLOGY", "Cloud broadcast and streaming SaaS", PLAT, PVT, NONE, EXP, "SAAS|CTV|BROADCAST|CLOUD", "SAAS|DIGITAL"),
    "FRACTAL": (IT, "DATA & AI SERVICES", "AI and advanced analytics services", SVC, PVT, NONE, EXP, "AI|ANALYTICS|DATA SCIENCE", "AI|IT SERVICES"),
    "MOBIKWIK": (DP, "FINTECH PLATFORM", "Digital payments and consumer lending", PLAT, PVT, NONE, CONS, "PAYMENTS|WALLET|FINTECH|UPI", "FINTECH|DIGITAL"),
    "RPTECH": (IT, "IT DISTRIBUTION", "Distribution of IT and computing products", DIST, PVT, NONE, IMP, "IT DISTRIBUTION|COMPONENTS", "IT HARDWARE"),
    "DLINKINDIA": (IT, "NETWORKING PRODUCTS", "Networking hardware distribution", DIST, MNC, NONE, IMP, "NETWORKING|ROUTERS|MNC", "IT HARDWARE"),
    "IVALUE": (IT, "IT DISTRIBUTION", "Value-added distribution of enterprise IT", DIST, PVT, NONE, IMP, "IT DISTRIBUTION|CYBERSECURITY|ENTERPRISE", "IT HARDWARE"),
    "NELCO": (TE, "SATELLITE COMMUNICATION", "VSAT and satellite connectivity", SVC, PVT, NONE, GOVT, "VSAT|SATCOM|TATA", "TELECOM|SATCOM"),

    # ---------------- business services ----------------
    "UDS": (BS, "FACILITY MANAGEMENT", "Integrated facility and business services", SVC, PVT, NONE, CONS, "FACILITY MANAGEMENT|STAFFING", "BUSINESS SERVICES"),
    "BLSE": (BS, "DIGITAL SERVICES", "E-governance and business correspondent services", SVC, PVT, NONE, GOVT, "EGOV|BC|CSC|DIGITAL", "GOVTECH"),
}


def main():
    df = pd.read_csv(MASTER, dtype={"SECURITY ID": str})
    cols = ["SECTOR", "INDUSTRY", "CORE BUSINESS", "BUSINESS_TYPE",
            "OWNERSHIP", "COMMODITY_EXPOSURE", "ECONOMIC_SENSITIVITY",
            "KEYWORDS", "THEMES"]

    unclassified = df["SECTOR"].isna()
    targets = set(df.loc[unclassified, "SYMBOL"])
    filled, skipped = 0, []

    for symbol, values in C.items():
        if symbol not in targets:
            skipped.append(symbol)
            continue
        row = df["SYMBOL"] == symbol
        for col, val in zip(cols, values):
            df.loc[row, col] = val
        # Classified, but NOT auto-enabled. The next morning run decides
        # SUBSCRIBE through the normal gates (price band, T2T, ETF,
        # liquidity, price >= Rs 200) like every other stock.
        df.loc[row, "SUBSCRIBE_REASON"] = (
            "classified 2026-07-26 -- awaiting next morning run for "
            "eligibility")
        filled += 1

    still_blank = df["SECTOR"].isna()
    df.loc[still_blank, "SUBSCRIBE_REASON"] = (
        "new listing -- unidentified, needs manual classification")

    df.to_csv(MASTER, index=False)

    print(f"classified      : {filled}")
    print(f"still blank     : {int(still_blank.sum())}")
    if skipped:
        print(f"not in file     : {skipped}")
    print()
    print("REMAINING UNIDENTIFIED (stay blocked):")
    print("  " + ", ".join(sorted(df.loc[still_blank, "SYMBOL"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
