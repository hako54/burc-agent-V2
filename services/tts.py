"""
TTS (Text-to-Speech) Servisi
ElevenLabs → Edge TTS → gTTS fallback zinciri.

Linux/Railway'de Edge TTS SSL sorunu yaşamaz, ama yerel Windows'ta
yaşanabilir. Bu oturum boyunca başarısız olan provider'lar atlanır.
"""

import asyncio
import os
import logging

log = logging.getLogger(__name__)

# Oturum durumu: Bir provider başarısız olursa sonraki çağrılarda atlanır
_session_state = {"edge_ok": None, "elevenlabs_ok": None}


def _tts_elevenlabs(text: str, out_path: str) -> bool:
    """ElevenLabs ile TTS. Başarılıysa True döner.
    API key yoksa veya hata olursa False."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return False

    # Oturumda daha önce başarısız olduysa atla
    if _session_state["elevenlabs_ok"] is False:
        return False

    try:
        import httpx
        from elevenlabs import ElevenLabs, save

        client = ElevenLabs(
            api_key=api_key,
            httpx_client=httpx.Client(verify=False, timeout=60),
        )
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
            voice_settings={
                "stability": 0.45,
                "similarity_boost": 0.80,
                "style": 0.40,
                "use_speaker_boost": True,
            },
        )
        save(audio, out_path)
        _session_state["elevenlabs_ok"] = True
        log.info(f"    ✅ ElevenLabs: {os.path.basename(out_path)}")
        return True
    except Exception as e:
        log.warning(f"    ⚠ ElevenLabs: {str(e)[:100]}")
        _session_state["elevenlabs_ok"] = False
        return False


def _tts_edge(text: str, out_path: str) -> bool:
    """Microsoft Edge TTS ile. Ücretsiz, kaliteli. Windows'ta SSL sorunu
    yaşayabilir — o durumda bu oturumda bir daha denenmez."""
    if _session_state["edge_ok"] is False:
        return False

    try:
        async def _run():
            import edge_tts
            voice = os.environ.get("EDGE_TTS_VOICE", "tr-TR-EmelNeural")
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
    """Google TTS (gTTS) — en güvenilir fallback. İnternet bağlantısı
    yeterli, SSL sorunu çıkarmaz."""
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
    """Metni seslendirir. Provider'lar sırasıyla denenir. Dosya yolu döner.
    Hepsi başarısız olursa exception fırlatır."""
    if not text or not text.strip():
        raise ValueError("TTS için boş metin verilemez")

    # Çağrı sırası: ElevenLabs (premium) → Edge (ücretsiz) → gTTS (son çare)
    for tts_fn in (_tts_elevenlabs, _tts_edge, _tts_gtts):
        if tts_fn(text, out_path):
            return out_path

    raise RuntimeError(
        "Tüm TTS servisleri başarısız. "
        "En az bir tanesi çalışmalı (gTTS internet bağlantısı ister)"
    )


def reset_session_state():
    """Oturum durumunu sıfırlar. Testlerde veya manuel tetiklemede kullanılabilir."""
    _session_state["edge_ok"] = None
    _session_state["elevenlabs_ok"] = None
