"""HTML and plain-text report generators."""

from __future__ import annotations

import html
import json
import re
import textwrap
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse

from dateutil import parser as date_parser


def _esc(text: str) -> str:
    return html.escape(text or "")


def format_date_human(raw: str | None) -> str:
    """Format ISO date for human-readable display."""
    if not raw:
        return "Date unknown"
    try:
        dt = date_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%A, %B %d, %Y at %H:%M UTC")
    except (ValueError, TypeError):
        return raw


def _story_summary(story: dict) -> str:
    raw = story.get("detailed_summary") or ""
    if not raw and not _read_more_links(story):
        raw = _best_summary_candidate(story)
    if raw:
        clean = _clean_summary_text(raw)
        if clean:
            title = _clean_summary_text(story.get("title") or "")
            if _looks_like_any_title(clean, story):
                return _generate_fallback_summary(story)
            return _trim_to_sentences(clean, max_words=260)
    return _generate_fallback_summary(story)


def _generate_fallback_summary(story: dict) -> str:
    """Generate a summary from title and sources when article extraction fails."""
    title = story.get("title") or ""
    sources = story.get("sources") or []
    sc = story.get("source_count", 1)

    if sources:
        source_str = sources[0]
        if len(sources) > 1:
            source_str += f" and {len(sources) - 1} other source{'s' if len(sources) > 2 else ''}"
        return f"Reported by {source_str}: {title}"

    return f"Story: {title}"


def _clean_summary_text(raw: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", html.unescape(raw or ""))
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = re.sub(r"\bContinue reading\b.*$", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\bRead more\b.*$", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\bThe post .+? appeared first on .+?\.$", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\s+([,.;:!?])", r"\1", clean)
    return clean


def _candidate_score(summary: str, title: str) -> int:
    clean = _clean_summary_text(summary)
    if not clean:
        return 0
    score = min(len(clean), 700)
    if _looks_like_title_only(clean, title):
        score -= 300
    if len(clean.split()) < 12:
        score -= 150
    if " - " in clean[:120]:
        score -= 40
    return score


def _looks_like_title_only(summary: str, title: str) -> bool:
    summary_clean = re.sub(r"\s[-|]\s+[^-|]{2,80}$", "", summary).strip().lower()
    title_clean = re.sub(r"\s[-|]\s+[^-|]{2,80}$", "", title).strip().lower()
    if not summary_clean or not title_clean:
        return False
    if summary_clean in title_clean or title_clean in summary_clean:
        return True
    if len(summary_clean.split()) > 26:
        return False
    return SequenceMatcher(None, summary_clean, title_clean).ratio() >= 0.86


def _looks_like_any_title(summary: str, story: dict) -> bool:
    titles = [story.get("title") or "", *(story.get("all_titles") or [])]
    return any(_looks_like_title_only(summary, title) for title in titles if title)


def _best_summary_candidate(story: dict) -> str:
    title = story.get("title") or ""
    candidates = list(story.get("all_summaries") or [])
    if story.get("summary"):
        candidates.append(story["summary"])
    if not candidates:
        return ""
    candidates_filtered = [c for c in candidates if c and not _looks_like_any_title(_clean_summary_text(c), story)]
    if candidates_filtered:
        return max(candidates_filtered, key=lambda c: _candidate_score(c, title))
    if candidates:
        return max(candidates, key=lambda c: _candidate_score(c, title))
    return ""


def _trim_to_sentences(text: str, *, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text

    sentences = re.split(r"(?<=[.!?])\s+", text)
    selected: list[str] = []
    count = 0
    for sentence in sentences:
        sentence_words = sentence.split()
        if not sentence_words:
            continue
        if selected and count + len(sentence_words) > max_words:
            break
        selected.append(sentence)
        count += len(sentence_words)

    if selected:
        trimmed = " ".join(selected).strip()
        if len(trimmed.split()) >= 18:
            return trimmed

    return " ".join(words[:max_words]).rsplit(" ", 1)[0].rstrip(",;:") + "..."


def _domain(url: str) -> str:
    host = urlparse(url or "").netloc
    return host.removeprefix("www.") if host else "original source"


def _read_more_links(story: dict, *, limit: int = 2) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in story.get("read_more_links") or []:
        url = item.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        links.append({"url": url, "source": item.get("source") or _domain(url)})
        if len(links) >= limit:
            return links

    sources = story.get("sources") or []
    urls = [story.get("url") or "", *(story.get("all_urls") or [])]
    for idx, url in enumerate(urls):
        if not url or url in seen:
            continue
        seen.add(url)
        links.append({"url": url, "source": sources[idx] if idx < len(sources) else _domain(url)})
        if len(links) >= limit:
            break
    return links


def _newsletter_brief(story: dict) -> dict[str, str]:
    title = story.get("title") or "AI news story"
    summary = _story_summary(story)
    sources = story.get("sources") or []
    sc = story.get("source_count", len(sources) or 1)
    social = story.get("social_fallback")

    if summary == "No summary available for this story.":
        summary = f"No detailed article summary could be extracted for: {title}"

    if social == "reddit":
        why = "Why it matters: Reddit traction is an early signal that builders and AI-watchers are already debating the practical impact."
    elif sc >= 3:
        why = f"Why it matters: Coverage across {sc} outlets suggests this is more than a one-off announcement and is worth watching."
    elif sc == 2:
        why = "Why it matters: Multiple outlets have picked it up, which usually means the story has broader product, policy, or market relevance."
    else:
        why = "Why it matters: It is a focused signal from a single source, useful for spotting emerging AI developments before they spread."

    source_line = ", ".join(sources[:4]) if sources else _domain(story.get("url") or "")
    if len(sources) > 4:
        source_line += f" + {len(sources) - 4} more"

    return {
        "takeaway": summary,
        "why": why,
        "source_line": source_line,
    }


def _format_html_read_more(story: dict) -> str:
    links = _read_more_links(story)
    if not links:
        return ""
    items = "".join(
        f'<li><a href="{_esc(link["url"])}" target="_blank" rel="noopener">{_esc(link["source"])}</a></li>'
        for link in links
    )
    return f'<div class="read-more"><strong>Read further:</strong><ol>{items}</ol></div>'


def _first_published(story: dict) -> str | None:
    return story.get("first_published") or story.get("date")


def generate_html_report(
    stories: list[dict],
    *,
    days: int,
    total_scanned: int,
    sources_used: list[str],
    verified_count: int,
    output_path: str,
) -> None:
    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    generated_date = now.strftime("%A, %B %d, %Y")
    n = len(stories)
    sources_str = ", ".join(sources_used[:8]) if sources_used else "RSS feeds"
    if len(sources_used) > 8:
        sources_str += f" + {len(sources_used) - 8} more"

    lead = stories[0] if stories else {}
    lead_title = _esc(lead.get("title") or "No stories selected")
    lead_url = _esc(lead.get("url") or "#")
    lead_brief = _newsletter_brief(lead) if lead else {
        "takeaway": "No matching AI stories were selected for this report.",
        "why": "Try increasing the date range or adding more RSS feeds.",
        "source_line": sources_str,
    }

    cards_html = []
    for story in stories:
        rank = story.get("rank", 0)
        sc = story.get("source_count", 1)
        social = story.get("social_fallback")
        is_reddit = social == "reddit"
        verified = sc >= 3 and not is_reddit
        brief = _newsletter_brief(story)

        badges_html = ""
        if verified:
            badges_html += '<span class="eyebrow-pill verified">Verified</span>'
        if is_reddit:
            badges_html += '<span class="eyebrow-pill social">Reddit signal</span>'

        first_pub = _first_published(story)
        first_pub_display = _esc(format_date_human(first_pub))
        takeaway = _esc(brief["takeaway"])
        why = _esc(brief["why"])
        source_line = _esc(brief["source_line"])
        hook = _esc(story.get("hook") or "")
        title = _esc(story.get("title") or "")
        url = _esc(story.get("url") or "#")
        sources = story.get("sources") or []
        read_more_html = _format_html_read_more(story)

        cards_html.append(
            f"""
    <article class="story-card">
      <div class="story-kicker">
        <span>Story {rank}</span>
        <span>{sc} source{'s' if sc != 1 else ''}</span>
        {badges_html}
      </div>
      <h2><a href="{url}" target="_blank" rel="noopener">{title}</a></h2>
      <p class="takeaway">{takeaway}</p>
      {read_more_html}

      {f'<p class="creator-hook"><span>Reel angle</span>{hook}</p>' if hook else ''}

      <details>
        <summary>Source notes</summary>
        <div class="metadata">
          <p><strong>First published:</strong> {first_pub_display}</p>
          <p><strong>Coverage:</strong> {source_line}</p>
          <div class="chips">
            {''.join(f'<span class="chip">{_esc(s)}</span>' for s in sources)}
          </div>
        </div>
      </details>
    </article>"""
        )

    cards_joined = "\n".join(cards_html)

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>The AI Sangh Brief — {generated_at}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --paper: #fbfaf7;
      --ink: #171717;
      --muted: #66635d;
      --rule: #ddd8ce;
      --accent: #0f766e;
      --accent-dark: #134e4a;
      --amber: #b45309;
      --panel: #ffffff;
    }}

    body {{
      font-family: Georgia, 'Times New Roman', serif;
      background: var(--paper);
      color: var(--ink);
      line-height: 1.65;
      margin: 0;
    }}

    a {{ color: inherit; text-decoration-color: rgba(15, 118, 110, 0.45); text-underline-offset: 3px; }}

    .page {{
      max-width: 920px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}

    header {{
      border-bottom: 2px solid var(--ink);
      padding-bottom: 26px;
      margin-bottom: 28px;
    }}

    .masthead {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      border-bottom: 1px solid var(--rule);
      padding-bottom: 18px;
      margin-bottom: 22px;
    }}

    .brand {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 0.78rem;
      font-weight: 800;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--accent-dark);
    }}

    h1 {{
      font-size: clamp(2.4rem, 7vw, 5.6rem);
      line-height: 0.92;
      font-weight: 500;
      margin-top: 10px;
      max-width: 760px;
    }}

    .dateline {{
      color: var(--muted);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 0.9rem;
      white-space: nowrap;
    }}

    .dek {{
      max-width: 720px;
      font-size: 1.16rem;
      color: #34322e;
      margin-bottom: 22px;
    }}

    .stats-bar {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      border: 1px solid var(--rule);
      background: var(--panel);
    }}

    .stat {{
      padding: 14px;
      border-right: 1px solid var(--rule);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}

    .stat:last-child {{ border-right: 0; }}

    .stat-value {{
      display: block;
      font-size: 1.35rem;
      font-weight: 800;
      color: var(--accent-dark);
      line-height: 1;
    }}

    .stat-label {{
      display: block;
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}

    .lead-story {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(220px, 0.65fr);
      gap: 28px;
      padding: 28px 0;
      border-bottom: 1px solid var(--rule);
      margin-bottom: 22px;
    }}

    .section-label {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      color: var(--accent);
      font-size: 0.78rem;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }}

    .lead-story h2 {{
      font-size: clamp(1.8rem, 4vw, 3.3rem);
      line-height: 1.03;
      font-weight: 500;
      margin-bottom: 14px;
    }}

    .lead-story p {{
      font-size: 1.06rem;
      color: #34322e;
    }}

    .editor-note {{
      border-left: 3px solid var(--accent);
      padding-left: 16px;
      color: var(--muted);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 0.94rem;
    }}

    .story-card {{
      background: var(--panel);
      border: 1px solid var(--rule);
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 16px;
      box-shadow: 0 10px 30px rgba(23, 23, 23, 0.04);
    }}

    .story-kicker {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 750;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}

    .story-kicker span {{
      border-right: 1px solid var(--rule);
      padding-right: 8px;
    }}

    .story-kicker span:last-child {{ border-right: 0; }}

    .story-card h2 {{
      font-size: clamp(1.35rem, 2.4vw, 2rem);
      line-height: 1.16;
      font-weight: 500;
      margin-bottom: 14px;
    }}

    .takeaway {{
      font-size: 1.02rem;
      margin-bottom: 12px;
      color: #2b2925;
    }}

    .read-more {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      border: 1px solid var(--rule);
      border-radius: 6px;
      padding: 12px 14px;
      margin-bottom: 14px;
      color: #34322e;
      font-size: 0.94rem;
    }}

    .read-more ol {{
      margin: 8px 0 0 20px;
    }}

    .read-more li {{
      padding-left: 4px;
      margin-top: 4px;
      word-break: break-word;
    }}

    .creator-hook {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      color: #4a3415;
      background: #fff7ed;
      border: 1px solid #fed7aa;
      border-radius: 6px;
      padding: 12px 14px;
      margin-bottom: 14px;
      font-size: 0.94rem;
    }}

    .creator-hook span {{
      display: block;
      color: var(--amber);
      font-size: 0.72rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 4px;
    }}

    .eyebrow-pill {{
      border: 1px solid var(--rule);
      border-radius: 999px;
      padding: 1px 8px;
    }}

    .eyebrow-pill.verified {{
      color: var(--accent-dark);
      border-color: #99d7cf;
    }}

    .eyebrow-pill.social {{
      color: var(--amber);
      border-color: #f4c48b;
    }}

    details {{
      border-top: 1px solid var(--rule);
      padding-top: 12px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}

    summary {{
      cursor: pointer;
      color: var(--accent-dark);
      font-weight: 750;
      font-size: 0.9rem;
    }}

    .metadata {{
      margin-top: 12px;
      color: var(--muted);
      font-size: 0.9rem;
    }}

    .metadata p {{ margin-bottom: 8px; }}

    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
    }}

    .chip {{
      background: #f2f0ea;
      border: 1px solid var(--rule);
      color: #4a4740;
      padding: 4px 8px;
      border-radius: 6px;
      font-size: 0.78rem;
    }}

    footer {{
      border-top: 2px solid var(--ink);
      margin-top: 30px;
      padding-top: 18px;
      color: var(--muted);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 0.86rem;
    }}

    @media (max-width: 720px) {{
      .page {{ padding: 22px 14px 36px; }}
      .masthead {{ align-items: flex-start; flex-direction: column; gap: 10px; }}
      .dateline {{ white-space: normal; }}
      .stats-bar {{ grid-template-columns: repeat(2, 1fr); }}
      .stat:nth-child(2) {{ border-right: 0; }}
      .stat:nth-child(-n+2) {{ border-bottom: 1px solid var(--rule); }}
      .lead-story {{ grid-template-columns: 1fr; gap: 16px; }}
      .story-card {{ padding: 18px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <header>
      <div class="masthead">
        <div>
          <div class="brand">AI Sangh</div>
          <h1>The AI Sangh Brief</h1>
        </div>
        <div class="dateline">{generated_date}<br>{generated_at}</div>
      </div>
      <p class="dek">A curated newsletter-style digest of the {n} most relevant AI stories from the last {days} day{'s' if days != 1 else ''}, with summaries built from the read-further articles whenever article links are available.</p>
      <div class="stats-bar">
        <div class="stat"><span class="stat-value">{total_scanned}</span><span class="stat-label">Stories scanned</span></div>
        <div class="stat"><span class="stat-value">{n}</span><span class="stat-label">Stories selected</span></div>
        <div class="stat"><span class="stat-value">{verified_count}</span><span class="stat-label">Verified stories</span></div>
        <div class="stat"><span class="stat-value">{len(sources_used)}</span><span class="stat-label">Sources used</span></div>
      </div>
    </header>

    <section class="lead-story">
      <div>
        <div class="section-label">Lead story</div>
        <h2><a href="{lead_url}" target="_blank" rel="noopener">{lead_title}</a></h2>
        <p>{_esc(lead_brief["takeaway"])}</p>
      </div>
      <aside class="editor-note">
        <div class="section-label">Editor's read</div>
        <p><strong>Source mix:</strong> {_esc(sources_str)}</p>
      </aside>
    </section>

    <main id="stories-container">
{cards_joined}
    </main>

    <footer>
      <p>Generated by AI Sangh. Open the article links for full reporting and source verification.</p>
      <p><a href="https://github.com/aisangh/news-update" target="_blank" rel="noopener">View project on GitHub</a></p>
    </footer>
  </div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc)


def generate_text_report(
    stories: list[dict],
    *,
    days: int,
    total_scanned: int,
    sources_used: list[str],
    verified_count: int,
    output_path: str,
) -> None:
    """Write a newsletter-style plain-text report for easy reading."""
    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    generated_date = now.strftime("%A, %B %d, %Y")
    sources_str = ", ".join(sources_used[:8]) if sources_used else "RSS feeds"
    if len(sources_used) > 8:
        sources_str += f" + {len(sources_used) - 8} more"

    lines = [
        "THE AI SANGH BRIEF",
        "A curated newsletter digest from AI Sangh",
        "",
        f"{generated_date} | {generated_at}",
        f"Coverage window: last {days} day{'s' if days != 1 else ''}",
        "",
        "AT A GLANCE",
        f"Stories scanned: {total_scanned}",
        f"Stories selected: {len(stories)}",
        f"Verified by 3+ sources: {verified_count}",
        f"Source mix: {sources_str}",
        "",
        "TOP STORIES",
        "=" * 72,
        "",
    ]

    for i, story in enumerate(stories, 1):
        rank = story.get("rank", i)
        sc = story.get("source_count", 1)
        title = story.get("title") or ""
        url = story.get("url") or ""
        first_pub = format_date_human(_first_published(story))
        brief = _newsletter_brief(story)
        hook = story.get("hook") or ""

        social = story.get("social_fallback")
        is_reddit = social == "reddit"
        verified = sc >= 3 and not is_reddit
        badge = "VERIFIED" if verified else ("REDDIT SIGNAL" if is_reddit else "WATCHLIST")

        lines.extend([
            f"{rank}. {title}",
            f"{badge} | {sc} source{'s' if sc != 1 else ''} | First published: {first_pub}",
            "",
            "What happened:",
        ])

        for line in textwrap.fill(brief["takeaway"], width=72).split("\n"):
            lines.append(f"  {line}")

        lines.extend([
            "",
            f"Sources: {brief['source_line']}",
            "Read further:",
        ])
        links = _read_more_links(story)
        if links:
            for link_idx, link in enumerate(links, 1):
                lines.append(f"  {link_idx}. {link['source']}: {link['url']}")
        else:
            lines.append(f"  1. {_domain(url)}: {url}")

        if hook:
            lines.append("Creator angle:")
            for line in textwrap.fill(hook, width=72).split("\n"):
                lines.append(f"  {line}")

        lines.extend([
            "",
            "-" * 72,
            "",
        ])

    lines.extend([
        "Generated by AI Sangh",
        "https://github.com/aisangh/news-update",
        "",
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def export_json(stories: list[dict], path: str, *, days: int) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "stories": [
            {
                **s,
                "first_published": _first_published(s),
                "first_published_display": format_date_human(_first_published(s)),
            }
            for s in stories
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
