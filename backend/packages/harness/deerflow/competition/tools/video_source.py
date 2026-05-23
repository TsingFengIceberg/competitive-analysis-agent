"""Video source extraction tools (P1) — YouTube transcripts, Bilibili subtitles.

Per COMPETITION_PLAN.md §4.2: extract product review opinions from video content.
Placeholder implementations — real extraction requires runtime data sources and API keys.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def extract_youtube_transcript(video_url: str, languages: list[str] | None = None) -> dict | None:
    """Extract transcript/subtitles from a YouTube video.

    Args:
        video_url: YouTube video URL (watch?v= or youtu.be/).
        languages: Preferred language codes, e.g. ['en', 'zh-Hans']. Default: ['en'].

    Returns:
        {title, transcript, language, duration_seconds, chapters[]} or None on failure.

    Production: youtube-transcript-api (MIT license).
    """
    logger.info("YouTube transcript extraction not yet configured for %s", video_url)
    return None


def extract_bilibili_info(bvid: str) -> dict | None:
    """Extract video metadata + subtitles from Bilibili.

    Args:
        bvid: Bilibili video BV ID (e.g. 'BV1xx411c7mD').

    Returns:
        {title, description, tags[], view_count, danmaku_count, subtitles_text} or None.

    Production: bilibili-api-python (MIT license).
    """
    logger.info("Bilibili info extraction not yet configured for %s", bvid)
    return None


def extract_video_opinions(transcript: str, target_products: list[str]) -> list[dict]:
    """Extract product comparison opinions from a video transcript using LLM.

    Args:
        transcript: Full video transcript text.
        target_products: Products to look for in the discussion.

    Returns:
        List of {product, opinion_type, statement, confidence, timestamp}.
        opinion_type: "feature_mention" | "comparison" | "review" | "pricing" | "prediction".

    Production: sends transcript to Doubao-Seed-2.0-lite with structured extraction prompt.
    """
    logger.info("Video opinion extraction not yet configured (%d products)", len(target_products))
    return []


def search_youtube_videos(query: str, max_results: int = 5) -> list[dict]:
    """Search YouTube for product review/analysis videos.

    Args:
        query: Search query, e.g. 'Cursor vs Copilot review 2026'.
        max_results: Max videos to return.

    Returns:
        List of {video_id, title, channel, published_at, duration, url}.

    Production: YouTube Data API v3 (requires API key).
    """
    logger.info("YouTube search not yet configured: %s", query)
    return []


def search_bilibili_videos(query: str, max_results: int = 5) -> list[dict]:
    """Search Bilibili for Chinese-language product review videos.

    Args:
        query: Search query in Chinese, e.g. 'Cursor 评测 2026'.
        max_results: Max videos to return.

    Returns:
        List of {bvid, title, author, play_count, published_at, url}.

    Production: bilibili-api-python search module.
    """
    logger.info("Bilibili search not yet configured: %s", query)
    return []
