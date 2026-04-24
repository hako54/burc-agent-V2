"""
İçerik Tipi Temel Sınıfı
Her content_type bu interface'i implemente eder. Pipeline her tip için
aynı şekilde çalışsa da, içerik üretim mantığı farklı olabilir.

Tipler: zodiac, motivation, recipe, history, psychology
"""

import os
import re
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)


class BaseContentType(ABC):
    """Tüm içerik tiplerinin miras alacağı temel sınıf."""

    # Alt sınıflar bunları override edecek
    type_id: str = "base"
    type_name: str = "Temel"
    type_icon: str = "✨"
    supports_auto: bool = False  # Otomatik scheduler için destekli mi
    supports_manual: bool = True  # Manuel topic girişi destekli mi

    def __init__(self, channel: dict):
        self.channel = channel
        self.channel_id = channel["id"]

    @abstractmethod
    def get_topics(self) -> list:
        """Dashboard'da gösterilecek konular listesi.
        Her topic şu formatta: {"key": "...", "name": "...", "icon": "...", "color": "..."}
        Zodiac için 12 burç, motivation için kategori, recipe için önerilen tarifler vs."""
        pass

    @abstractmethod
    def build_prompt(self, topic_key: str,
                     custom_topic: str = None,
                     used_themes: list = None) -> str:
        """LLM'e gidecek prompt'u oluştur.
        topic_key: Seçilen önceden tanımlı konu (koç, başarı, kek vs.)
        custom_topic: Kullanıcının yazdığı özel konu metni (manuel mod)"""
        pass

    @abstractmethod
    def get_visual_queries(self, topic_key: str,
                           content: dict = None) -> list:
        """Pixabay/Pexels için görsel arama sorguları."""
        pass

    @abstractmethod
    def get_theme_colors(self, topic_key: str,
                         content: dict = None) -> dict:
        """Video teması (accent_color, background_color)."""
        pass

    def get_intro_text(self, topic_key: str, content: dict = None) -> str:
        """Videonun giriş seslendirmesi."""
        return f"{self.channel.get('name', '')} günlük içerik"

    def get_outro_text(self, topic_key: str, content: dict = None) -> str:
        """Outro metni (abone ol vs.)."""
        return "Abone ol · Her gün yeni içerik"

    def format_title(self, topic_key: str, content: dict) -> str:
        """YouTube başlığı (max 100 karakter)."""
        return content.get("title", self.channel.get("name", ""))[:100]

    def format_description(self, topic_key: str, content: dict) -> str:
        """YouTube açıklaması."""
        desc = content.get("description", "")
        hashtags = content.get("hashtags", [])
        if hashtags:
            desc = desc + "\n\n" + " ".join(hashtags[:15])
        return desc

    def get_tags(self, topic_key: str, content: dict) -> list:
        """YouTube tagleri."""
        return content.get("tags", [])[:15]

    def get_lucky_card(self, topic_key: str, content: dict) -> Optional[dict]:
        """Video sonunda gösterilecek 3 sütunlu bilgi kartı.
        Sadece bazı tipler için (zodiac). None dönerse kart gösterilmez.
        Format: {'col1': ('label', 'value'), 'col2': (...), 'col3': (...)}"""
        return None


def get_content_type(type_id: str, channel: dict) -> BaseContentType:
    """Tip ID'sinden uygun sınıfı döndürür. Tanımsız tip için zodiac'a düşer."""
    from content_types.zodiac import ZodiacType
    from content_types.motivation import MotivationType

    registry = {
        "zodiac": ZodiacType,
        "motivation": MotivationType,
        # ileride eklenecek:
        # "recipe": RecipeType,
        # "history": HistoryType,
        # "psychology": PsychologyType,
    }
    cls = registry.get(type_id, ZodiacType)
    return cls(channel)


def available_types() -> dict:
    """UI için tüm tipleri meta bilgileriyle döner."""
    from content_types.zodiac import ZodiacType
    from content_types.motivation import MotivationType

    types = [ZodiacType, MotivationType]
    return {
        t.type_id: {
            "id": t.type_id,
            "name": t.type_name,
            "icon": t.type_icon,
            "supports_auto": t.supports_auto,
            "supports_manual": t.supports_manual,
        }
        for t in types
    }
