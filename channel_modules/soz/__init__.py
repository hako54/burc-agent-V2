"""Söz kanalı modülü — Stok video + ElevenLabs TTS pipeline."""
from .config import (
    CHANNEL_META, VOICE_CONFIG, VIDEO_STYLE, THEMES, all_mood_tags,
)
from .content import (
    get_topics,
    build_prompt,
    match_theme,
    get_visual_queries,
    get_face_queries,
    get_theme_colors,
    get_intro_text,
    get_outro_text,
    get_lucky_card,
    format_title,
    format_description,
    get_tags,
)
