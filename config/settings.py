from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
METADATA_FILE = BASE_DIR / "metadata.json"

REDDIT_DATA_DIR = DATA_DIR / "reddit"
REDDIT_COMMENTS_DATA_DIR = DATA_DIR / "reddit_comments"
KNOWYOURMEME_DATA_DIR = DATA_DIR / "knowyourmeme"
IMGFLIP_DATA_DIR = DATA_DIR / "imgflip"

REDDIT_SUBREDDITS = [
    # tier 1: biggest general-purpose meme hubs (most recognized)
    "memes", "dankmemes", "me_irl", "meirl", "2meirl4meirl",
    "wholesomememes", "funny", "AdviceAnimals", "shitposting",
    "MemeEconomy", "memesopdidnotlike", "dogelore", "HolUp",
    # tier 2: twitter/facebook screenshot humor (top searched formats)
    "WhitePeopleTwitter", "BlackPeopleTwitter", "NonPoliticalTwitter",
    "ScottishPeopleTwitter", "IrishPeoplesTwitter", "tumblr", "teenagers",
    "insanepeoplefacebook", "oldpeoplefacebook", "forwardsfromgrandma",
    # tier 3: political humor (highest raw post volume)
    "PoliticalHumor", "trump", "politicalmemes", "conservativememes",
    "libertarianmemes", "LeopardsAteMyFace", "MurderedByWords",
    "antiwork", "ABoringDystopia", "LateStageCapitalism",
    # tier 4: mainstream gaming & fandom
    "gaming", "pcmasterrace", "nintendo", "PrequelMemes", "HistoryMemes",
    "marvelmemes", "spidermanmemes", "harrypotter", "gameofthrones",
    "freefolk", "pokemonmemes", "MinecraftMemes", "BikiniBottomTwitter",
    "SpongebobMemes", "simpsonsshitposting", "southparkmemes",
    "ProgrammerHumor", "doctorwho",
    # tier 5: classic formats & relatable
    "starterpacks", "therewasanattempt", "Unexpected", "facepalm",
    "MadeMeSmile", "EyeBleach", "WatchPeopleDieInside",
    "KidsAreFuckingStupid", "suspiciouslyspecific", "confidentlyincorrect",
    "iamverysmart", "iam14andthisisdeep", "LostRedditor", "InstantRegret",
    "terriblefacebookmemes", "comedyheaven", "BoneHurtingJuice",
    "surrealmemes", "ComedyNecrophilia", "okbuddyretard",
    # template sources (essential: canonical blank formats)
    "MemeTemplatesOfficial", "memesoundless", "BlankTemplatesForMemes",
]

# niche tail: crawled ONLY if the 50k target isn't reached by the mainstream
# list above (collector processes in order and stops at target)
REDDIT_SUBREDDITS_NICHE = [
    "animememes", "Animemes", "wholesomeanimemes", "catmemes", "dogmemes",
    "gamingmemes", "DC_Cinematic", "StarWarsMemes", "lotrmemes",
    "sequelmemes", "OTmemes", "OTMemesAndPrequels", "dankchristianmemes",
    "physicsmemes", "mathmemes", "chemistrymemes", "sciencememes",
    "engineeringmemes", "spacememes", "bioniclememes",
    "reactionpictures", "reactionsformats", "relatablememes",
    "Cringetopia", "cringepics", "196",
    "pcgaming", "playstation", "xbox", "nintendomemes", "GamingCirclejerk",
    "GamingDetails", "destinythegame", "techsupportmemes",
    "TalesFromTechSupport", "okbuddybaka", "okbuddyvicodin",
    "okbuddychicanery", "okbuddylmao", "traaaaaaannnnnnnnnns",
    "gaybrosofbattlefront", "marveltv", "meirlformeirl", "okbuddyholly",
    "ABCDesis", "GenZ", "zoomers", "theocho", "pointlessindecision",
    "wheredidthesodago", "englishpeopletwitter", "welcometothelldome",
    "comics", "webcomics", "funnycomics", "comicsans", "formemers",
]

REDDIT_SUBREDDITS = REDDIT_SUBREDDITS + REDDIT_SUBREDDITS_NICHE

# per-subreddit image cap for a full run
REDDIT_MAX_PER_SUB = 3000
# don't go older than this when walking history back
# extended from 2023 -> 2018 to unlock years of untapped meme history
# (the 2023 floor had exhausted every sub at only ~24.7k of the 50k target)
REDDIT_DATE_FLOOR = "2018-01-01"

# ---------------------------------------------------------------------------
# CURATED mode: the subreddits that actually teach a model "how memes work"
# (diverse formats + template sources). Kept small on purpose.
# ---------------------------------------------------------------------------
REDDIT_CURATED_SUBREDDITS = [
    # canonical captioned meme streams
    "memes", "dankmemes",
    # classic distinct formats
    "me_irl", "AdviceAnimals", "wholesomememes",
    "terriblefacebookmemes", "starterpacks",
    # template / format sources (essential for generation)
    "MemeTemplatesOfficial", "BlankTemplatesForMemes", "memesoundless",
    # reactions / relatable
    "reactionpictures", "reactionsformats", "relatablememes",
    # one fandom for format diversity
    "PrequelMemes",
]
REDDIT_CURATED_MAX_PER_SUB = 2000

# Curated quality gates (applied at ingest and when curating the catalog)
QUALITY_MIN_RESOLUTION = (400, 400)   # drop tiny images
QUALITY_MIN_FILE_SIZE_KB = 20        # drop blank / textless images
QUALITY_MIN_SCORE = 0.12              # drop obscure, low-engagement posts
# templates carry 0 upvotes so they score low by design -> exempt them
TEMPLATE_SUBREDDITS = {
    "memetemplatesofficial", "blanktemplatesformemes", "memesoundless",
}
TEMPLATE_SOURCES = {"imgflip"}

SUBREDDIT_META = {
    "memes": {"category": "general", "audience": "mainstream"},
    "dankmemes": {"category": "general", "audience": "gen_z"},
    "me_irl": {"category": "relatable", "audience": "gen_z_millennial"},
    "AdviceAnimals": {"category": "classic_macro", "audience": "millennial"},
    "wholesomememes": {"category": "wholesome", "audience": "broad"},
    "PrequelMemes": {"category": "fandom", "audience": "star_wars_fans"},
    "HistoryMemes": {"category": "niche_topic", "audience": "history_buffs"},
    "ProgrammerHumor": {"category": "niche_professional", "audience": "developers"},
    "Animemes": {"category": "fandom", "audience": "anime_fans"},
    "MinecraftMemes": {"category": "gaming", "audience": "minecraft_players"},
    "shitposting": {"category": "shitpost", "audience": "gen_z"},
    "okbuddyretard": {"category": "ironic_shitpost", "audience": "gen_z"},
    "ComedyNecrophilia": {"category": "ironic_shitpost", "audience": "meme_connoisseurs"},
    "surrealmemes": {"category": "absurdist", "audience": "art_house_internet"},
    "BoneHurtingJuice": {"category": "anti_meme", "audience": "meme_connoisseurs"},
    "comedyheaven": {"category": "so_bad_its_good", "audience": "gen_z_millennial"},
    "terriblefacebookmemes": {"category": "cringe", "audience": "young_mocking_boomer"},
    "starterpacks": {"category": "relatable_format", "audience": "broad"},
    "196": {"category": "shitpost", "audience": "very_online_gen_z"},
    "gamingmemes": {"category": "gaming", "audience": "gamers"},
    "animememes": {"category": "fandom", "audience": "anime_fans"},
    "dankchristianmemes": {"category": "niche_topic", "audience": "christians"},
    "physicsmemes": {"category": "niche_professional", "audience": "stem_students"},
    "mathmemes": {"category": "niche_professional", "audience": "stem_students"},
    "chemistrymemes": {"category": "niche_professional", "audience": "stem_students"},
    "bioniclememes": {"category": "fandom", "audience": "nostalgia_niche"},
    "lotrmemes": {"category": "fandom", "audience": "lotr_fans"},
    "sequelmemes": {"category": "fandom", "audience": "star_wars_fans"},
    "OTmemes": {"category": "fandom", "audience": "star_wars_fans"},
    "OTMemesAndPrequels": {"category": "fandom", "audience": "star_wars_fans"},
    "StarWarsMemes": {"category": "fandom", "audience": "star_wars_fans"},
    "marvelmemes": {"category": "fandom", "audience": "marvel_fans"},
    "DC_Cinematic": {"category": "fandom", "audience": "dc_fans"},
    "spidermanmemes": {"category": "fandom", "audience": "spiderman_fans"},
    "pokemonmemes": {"category": "gaming", "audience": "pokemon_fans"},
    "BikiniBottomTwitter": {"category": "fandom", "audience": "spongebob_fans"},
    "SpongebobMemes": {"category": "fandom", "audience": "spongebob_fans"},
    "simpsonsshitposting": {"category": "fandom", "audience": "simpsons_fans"},
    "southparkmemes": {"category": "fandom", "audience": "southpark_fans"},
    "MemeTemplatesOfficial": {"category": "template", "audience": "meme_creators"},
    "memesoundless": {"category": "template", "audience": "meme_creators"},
    "BlankTemplatesForMemes": {"category": "template", "audience": "meme_creators"},
    "reactionpictures": {"category": "reaction", "audience": "meme_creators"},
    "reactionsformats": {"category": "reaction", "audience": "meme_creators"},
    "relatablememes": {"category": "relatable", "audience": "broad"},
    "teenagers": {"category": "relatable", "audience": "teens"},
    "tumblr": {"category": "social_media_screenshot", "audience": "tumblr_users"},
    "WhitePeopleTwitter": {"category": "social_media_screenshot", "audience": "twitter_users"},
    "BlackPeopleTwitter": {"category": "social_media_screenshot", "audience": "twitter_users"},
    "therewasanattempt": {"category": "fail humor", "audience": "broad"},
    "Unexpected": {"category": "twist_humor", "audience": "broad"},
    "facepalm": {"category": "cringe", "audience": "broad"},
    "Cringetopia": {"category": "cringe", "audience": "gen_z"},
    "cringepics": {"category": "cringe", "audience": "gen_z"},
    "catmemes": {"category": "animals", "audience": "pet_lovers"},
    "dogmemes": {"category": "animals", "audience": "pet_lovers"},
    "wholesomeanimemes": {"category": "wholesome", "audience": "anime_fans"},
    "MadeMeSmile": {"category": "wholesome", "audience": "broad"},
}

DEFAULT_SUB_META = {"category": "general", "audience": "broad"}

MIN_RESOLUTION = (300, 300)
SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE_MB = 10

# ---------------------------------------------------------------------------
# RETRIEVAL / SEARCH CONFIG
# All paths are env-overridable so the same code runs locally AND on Colab
# (where images live on a mounted Drive and the repo is git-cloned elsewhere).
# ---------------------------------------------------------------------------

# Best open-source models (run on Colab/Kaggle GPU; size is not a concern).
EMBED_MODEL = "BAAI/bge-large-en-v1.5"          # 1024-dim sentence embeddings
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"        # cross-encoder reranker
# bge models require this query prefix for retrieval tasks.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# How many to return / how many candidates to rerank.
TOP_K = 6
RERANK_CANDIDATES = 30

import os as _os


def _env(name, default):
    """Read an env var, stripped (cmd's `set VAR=val &&` leaves trailing spaces)."""
    v = _os.environ.get(name, default)
    return v.strip() if isinstance(v, str) else v


# ROOT = where the code/repo lives. Images may live elsewhere (e.g. Drive).
ROOT = _env("MAKEMEME_ROOT", str(BASE_DIR))
# Where the meme images actually are (local data/ or Colab Drive mount).
IMAGES_DIR = _env("MAKEMEME_IMAGES", str(DATA_DIR))
# Catalog file (curated is richer: 24k vs 3.9k).
CATALOG_FILE = _env(
    "MAKEMEME_CATALOG", str(BASE_DIR / "curated_metadata.json")
)
# Where the built index + artifacts go.
INDEX_DIR = _env("MAKEMEME_INDEX", str(BASE_DIR / "search" / "index"))
OCR_CACHE_FILE = _env("MAKEMEME_OCR", str(BASE_DIR / "ocr_cache.json"))
MEMES_JSON = _env("MAKEMEME_MEMES", str(_os.path.join(INDEX_DIR, "memes.json")))
VECTORS_NPY = _env("MAKEMEME_VECTORS", str(_os.path.join(INDEX_DIR, "vectors.npy")))


def meme_key(m: dict) -> str:
    """Stable id used for OCR cache + index, across both catalog formats."""
    return m.get("id") or m.get("source_id") or m.get("source_url")


def resolve_image_path(image_path: str):
    """Resolve a catalog image_path to a real file under IMAGES_DIR.

    Catalog stores Windows-style paths like 'data\\reddit\\x.jpeg'. We strip a
    leading 'data/' so it joins cleanly with IMAGES_DIR (which already points
    at the data root). Returns the path if the file exists, else None.
    """
    if not image_path:
        return None
    rel = image_path.replace("\\", "/")
    if rel.startswith("data/"):
        rel = rel[len("data/"):]
    p = _os.path.join(IMAGES_DIR, rel)
    return p if _os.path.exists(p) else None

