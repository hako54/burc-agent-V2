"""
TTS (Text-to-Speech) Servisi — Kanal bazlı voice config destekli
ElevenLabs → Edge TTS → gTTS fallback zinciri.

Çağrı:
    generate_tts(text, out_path, voice_config={
        "voice_id": "...", "stability": 0.5, "style": 0.35, "speed": 0.95
    })

voice_config None ise varsayılanlar kullanılır.
"""

import asyncio
import os
import logging

log = logging.getLogger(__name__)

_session_state = {"edge_ok": None, "elevenlabs_ok": None}


def _default_voice_config() -> dict:
    return {
        "voice_id": os.environ.get("ELEVENLABS_VOICE_ID",
                                   "21m00Tcm4TlvDq8ikWAM"),  # Rachel
        "stability": 0.50,
        "style": 0.35,
        "speed": 0.95,
        "similarity_boost": 0.75,
    }


def _tts_elevenlabs(text: str, out_path: str,
                    voice_config: dict = None) -> bool:
    """ElevenLabs ile TTS. voice_config: kanal bazlı ses ayarları."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return False
    if _session_state["elevenlabs_ok"] is False:
        return False

    vc = {**_default_voice_config(), **(voice_config or {})}

    try:
        import httpx
        from elevenlabs import ElevenLabs, save

        client = ElevenLabs(
            api_key=api_key,
            httpx_client=httpx.Client(verify=False, timeout=90),
        )
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=vc["voice_id"],
            model_id="eleven_multilingual_v2",
            voice_settings={
                "stability": vc["stability"],
                "similarity_boost": vc.get("similarity_boost", 0.75),
                "style": vc["style"],
                "use_speaker_boost": True,
            },
        )
        save(audio, out_path)
        _session_state["elevenlabs_ok"] = True
        log.info(f"    ✅ ElevenLabs ({vc['voice_id'][:8]}…): {os.path.basename(out_path)}")
        return True
    except Exception as e:
        err_msg = str(e)
        log.warning(f"    ⚠ ElevenLabs: {err_msg[:150]}")
        if any(x in err_msg.lower() for x in
               ["quota", "billing", "unauthorized", "invalid", "forbidden"]):
            _session_state["elevenlabs_ok"] = False
        return False


def _tts_edge(text: str, out_path: str) -> bool:
    """Microsoft Edge TTS — ücretsiz fallback."""
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
    """Google TTS — en güvenilir son çare."""
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


def generate_tts(text: str, out_path: str,
                 voice_config: dict = None) -> str:
    """Metni seslendirir. voice_config kanal bazlı ses ayarlarını içerir.

    voice_config örneği:
        {"voice_id": "...", "stability": 0.5, "style": 0.4, "speed": 1.0}
    """
    if not text or not text.strip():
        raise ValueError("TTS için boş metin verilemez")

    # 1) ElevenLabs
    if _tts_elevenlabs(text, out_path, voice_config=voice_config):
        return out_path
    # 2) Edge
    if _tts_edge(text, out_path):
        return out_path
    # 3) gTTS
    if _tts_gtts(text, out_path):
        return out_path

    raise RuntimeError(
        "Tüm TTS servisleri başarısız. "
        "En az birinin çalışması gerekir."
    )


def reset_session_state():
    _session_state["edge_ok"] = None
    _session_state["elevenlabs_ok"] = None
