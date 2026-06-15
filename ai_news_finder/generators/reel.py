"""Template-based Instagram Reel content generation — no AI API calls."""

import hashlib
import re

COMPANIES = [
    "OpenAI",
    "Google",
    "Meta",
    "Microsoft",
    "Apple",
    "Amazon",
    "Anthropic",
    "Nvidia",
    "Tesla",
    "DeepMind",
    "Mistral",
    "Cohere",
    "Stability AI",
    "Runway",
]

VERBS = ["launched", "unveiled", "released", "announced", "introduced"]
IMPACTS = [
    "changes EVERYTHING about how we work",
    "could reshape the entire AI industry",
    "is making developers rethink their stack",
    "might be the biggest AI drop this year",
]
ACTIONS = ["shipped a major update", "made a huge move", "dropped a surprise release"]


def _seed(text: str) -> int:
    return int(hashlib.md5(text.encode()).hexdigest(), 16)


def extract_company(title: str) -> str:
    for company in COMPANIES:
        if company.lower() in title.lower():
            return company
    words = re.findall(r"\b[A-Z][a-zA-Z]+\b", title)
    return words[0] if words else "AI"


def _title_short(title: str, max_len: int = 60) -> str:
    t = title.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3].rsplit(" ", 1)[0] + "..."


def _extract_topic(title: str) -> str:
    lower = title.lower()
    for kw in ("gpt", "claude", "gemini", "llm", "regulation", "funding", "chip", "model"):
        if kw in lower:
            return kw.upper() if kw in ("gpt", "llm") else kw.title()
    return _title_short(title, 40)


def generate_hook(story: dict) -> str:
    title = story.get("title") or "AI news"
    company = extract_company(title)
    topic = _extract_topic(title)
    title_short = _title_short(title)
    idx = _seed(title) % 5

    templates = [
        f"🤯 {company} just {VERBS[_seed(title + 'v') % len(VERBS)]} something that {IMPACTS[_seed(title + 'i') % len(IMPACTS)]}",
        f"🚨 Breaking: {title_short} — here's what you need to know",
        f"💡 Why {topic} is the most important AI story this week",
        f"🔥 The biggest {topic} story right now — the AI world is talking about this",
        f"👀 {company} quietly {ACTIONS[_seed(title + 'a') % len(ACTIONS)]} and nobody is talking about it",
    ]
    hook = templates[idx]
    words = hook.split()
    if len(words) > 15:
        hook = " ".join(words[:15])
    return hook


def generate_caption(story: dict) -> str:
    title = story.get("title") or ""
    summary = (story.get("summary") or "").strip()
    sources = story.get("sources") or []
    source_note = ", ".join(sources[:3]) if sources else "multiple outlets"

    if summary:
        what = summary if len(summary) < 200 else summary[:197] + "..."
    else:
        what = title

    para1 = f"📰 {what}"
    para2 = (
        f"This story is gaining traction across {source_note} — "
        "a signal that it's worth paying attention to if you follow AI."
    )
    para3 = "Why it matters: AI moves fast, and stories like this shape what tools, rules, and products hit the market next."
    cta = "Drop a 🤖 if you want more breakdowns like this. Follow for daily AI updates 🤖"

    caption = f"{para1}\n\n{para2}\n\n{para3}\n\n{cta}"
    words = caption.split()
    if len(words) > 150:
        caption = " ".join(words[:150])
    return caption


def _story_hashtags(story: dict) -> list[str]:
    title = (story.get("title") or "").lower()
    tags = ["#AI", "#ArtificialIntelligence", "#Tech", "#Technology", "#AINews"]
    extra_map = [
        ("openai", "#OpenAI"),
        ("gpt", "#ChatGPT"),
        ("claude", "#Claude"),
        ("gemini", "#Gemini"),
        ("anthropic", "#Anthropic"),
        ("nvidia", "#Nvidia"),
        ("regulation", "#AIRegulation"),
        ("funding", "#Startup"),
        ("startup", "#AIStartup"),
        ("robot", "#Robotics"),
        ("chip", "#AIChips"),
        ("llm", "#LLM"),
        ("agent", "#AIAgents"),
        ("safety", "#AISafety"),
        ("microsoft", "#Microsoft"),
        ("google", "#Google"),
        ("meta", "#Meta"),
        ("mistral", "#Mistral"),
        ("video", "#GenerativeAI"),
        ("model", "#AIModels"),
    ]
    for needle, tag in extra_map:
        if needle in title and tag not in tags:
            tags.append(tag)
    filler = [
        "#MachineLearning",
        "#DeepLearning",
        "#Innovation",
        "#FutureTech",
        "#TechNews",
        "#Reels",
        "#InstagramReels",
        "#Viral",
        "#Trending",
        "#TechTok",
    ]
    for tag in filler:
        if len(tags) >= 25:
            break
        if tag not in tags:
            tags.append(tag)
    return tags[:25]


def generate_hashtags(story: dict) -> str:
    return " ".join(_story_hashtags(story))


def generate_reel_content(story: dict) -> dict:
    """Attach hook, caption, hashtags to a story dict (in place)."""
    story["hook"] = generate_hook(story)
    story["caption"] = generate_caption(story)
    story["hashtags"] = generate_hashtags(story)
    return story
