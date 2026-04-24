"""
TTS (Text-to-Speech) Servisi
ElevenLabs → Edge TTS → gTTS fallback zinciri.

ElevenLabs Türkçe desteği çok iyi — gerçek insan sesi gibi.
Varsayılan ses: Rachel (warm, narrative female).
Kullanıcı tercih ederse ELEVENLABS_VOICE_ID ile değiştirebilir.

Turkish için önerilen sesler:
- Rachel (21m00Tcm4TlvDq8ikWAM) — sıcak anlatımcı
- Bella (EXAVITQu4vr4xnSDxMaL) — yumuşak genç kadın
- Aria (9BWtsMINqrJLrRacOk9x) — duygusal empatik
- Matilda (XrExE9yKIg1WjnnlVkGX) — tatlı, naif
"""

import asyncio
import os
import logging

log = logging.getLogger(__name__)

# Oturum durumu — bir provider bu oturumda başarısız olduysa atlanır
_session_state = {"edge_ok": None, "elevenlabs_ok": None}


def _tts_elevenlabs(text: str, out_path: str) -> bool:
    """ElevenLabs ile TTS. Türkçe için en iyi kalite.
    Başarılıysa True, key yoksa/hata varsa False döner."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return False

    # Oturumda başarısız olduysa atla
    if _session_state["elevenlabs_ok"] is False:
        return False

    try:
        import httpx
        from elevenlabs import ElevenLabs, save

        client = ElevenLabs(
            api_key=api_key,
            httpx_client=httpx.Client(verify=False, timeout=90),
        )

        # Kullanıcı özel ses seçtiyse onu kullan, yoksa Rachel
        voice_id = os.environ.get(
            "ELEVENLABS_VOICE_ID",
            "21m00Tcm4TlvDq8ikWAM",  # Rachel - sıcak anlatımcı
        )

        # Türkçe için optimize edilmiş voice ayarları
        # stability: 0.50 = doğal + duygusal dengeli
        # similarity_boost: 0.75 = orijinal sese yakınlık
        # style: 0.35 = biraz ekspresyon, ama abartmadan (naif hissi)
        # speed: 0.95 = hafif yavaş — astroloji için daha akıcı
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",  # Türkçe'yi en iyi destekleyen
            voice_settings={
                "stability": 0.50,
                "similarity_boost": 0.75,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        )
        save(audio, out_path)
        _session_state["elevenlabs_ok"] = True
        log.info(f"    ✅ ElevenLabs: {os.path.basename(out_path)}")
        return True
    except Exception as e:
        err_msg = str(e)
        log.warning(f"    ⚠ ElevenLabs: {err_msg[:150]}")
        # Quota / billing / auth hataları — oturumda bir daha deneme
        # Ama network/timeout'larda bir şans daha verelim
        if any(x in err_msg.lower() for x in
               ["quota", "billing", "unauthorized", "invalid", "forbidden"]):
            _session_state["elevenlabs_ok"] = False
        return False


def _tts_edge(text: str, out_path: str) -> bool:
    """Microsoft Edge TTS. Ücretsiz, kaliteli (ElevenLabs'tan sonra ikinci).
    Windows'ta SSL sorunu yaşayabilir ama Linux/Railway'de çalışır."""
    if _session_state["edge_ok"] is False:
        return False

    try:
        async def _run():
            import edge_tts
            voice = os.environ.get("EDGE_TTS_VOICE", "tr-TR-EmelNeural")
            # Rate +3% = hafif hızlı, doğal tempo
            comm = edge_tts.Communicate(text=text, voice=voice, rate="+3%")
            await comm.save(out_path)

        asyncio.run(_run())
        if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
            _session_state["edge_ok"] = True
            log.info(f"    ✅ Edge TTS: {os.path.basename(out_path)}")
            return True
        return False
    except Exception as e:
        log.warning(f"    ⚠ Edge TTS: {str(e)[:100]}")
        _session_state["edge_ok"] = False
        return False


def _tts_gtts(text: str, out_path: str) -> bool:
    """Google TTS (gTTS) — en güvenilir son çare. Robotik ama hiç çökmez."""
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="tr", slow=False)
        tts.save(out_path)
        log.info(f"    ✅ gTTS: {os.path.basename(out_path)}")
        return True
    except ImportError:
        log.error("gTTS kurulu değil. pip install gTTS")
        return False
    except Exception as e:
        log.error(f"gTTS hata: {e}")
        return False


def generate_tts(text: str, out_path: str) -> str:
    """Metni seslendirir. Provider sırası:
    1. ElevenLabs (en kaliteli, ücretli)
    2. Edge TTS (ücretsiz, doğal)
    3. gTTS (son çare, robotik ama güvenilir)
    """
    if not text or not text.strip():
        raise ValueError("TTS için boş metin verilemez")

    for tts_fn in (_tts_elevenlabs, _tts_edge, _tts_gtts):
        if tts_fn(text, out_path):
            return out_path

    raise RuntimeError(
        "Tüm TTS servisleri başarısız. "
        "En az bir tanesi çalışmalı (gTTS internet bağlantısı ister)."
    )


def reset_session_state():
    """Oturum durumunu sıfırlar. Yeni deployment veya manuel reset için."""
    _session_state["edge_ok"] = None
    _session_state["elevenlabs_ok"] = None
