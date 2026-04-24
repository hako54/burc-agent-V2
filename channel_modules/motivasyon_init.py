"""Motivasyon kanalı modülü."""
from .config import CHANNEL_META, VOICE_CONFIG, CATEGORIES
from .content import get_topics, build_prompt, get_visual_queries, \
    get_theme_colors, get_intro_text, get_outro_text, get_lucky_card, \
    format_title, format_description, get_tags
