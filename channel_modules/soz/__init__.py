"""Söz kanalı modülü — HeyGen tabanlı AI avatar videoları."""
from .config import CHANNEL_META, HEYGEN_CONFIG, THEMES, all_mood_tags
from .content import (
    get_topics,
    build_prompt,
    match_theme,
    pick_look_id,
    get_theme_info,
    format_title,
    format_description,
    get_tags,
    get_visual_queries,
    get_theme_colors,
    get_intro_text,
    get_outro_text,
    get_lucky_card,
)
