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
import threading
import time

log = logging.getLogger(__name__)

# Servis başına "şu zamana kadar atla" bilgisi. Eskiden tek bir hatada
# servis süreç yeniden başlayana kadar (günlerce) kalıcı kapanıyordu.
# Artık hata türüne göre süreli bekleme var; süre dolunca tekrar denenir.
_COOLDOWN_LONG = 3600   # yetki / kota / ödeme sorunu
_COOLDOWN_SHORT = 120   # ağ hatası, aşırı yük, 5xx
_TRANSIENT_LIMIT = 3     # üst üste bu kadar geçici hatadan sonra bekle
_skip_until = {"elevenlabs": 0.0, "edge": 0.0}
_fail_streak = {"elevenlabs": 0, "edge": 0}
_lock = threading.Lock()


def _available(service: str) -> bool:
    with _lock:
        return time.monotonic() >= _skip_until[service]


def _cool_down(service: str, seconds: int, reason: str):
    with _lock:
        _skip_until[service] = time.monotonic() + seconds
    log.warning(f"    ⏸ {service} {seconds // 60 or 1} dk atlanacak: "
                f"{reason[:120]}")


def _transient_failure(service: str, reason: str):
    """Geçici hata: tek seferlik hatada servisi kapatma (aynı videoda ses
    değişmesin); üst üste _TRANSIENT_LIMIT hatadan sonra kısa bekle."""
    with _lock:
        _fail_streak[service] += 1
        streak = _fail_streak[service]
    if streak >= _TRANSIENT_LIMIT:
        _cool_down(service, _COOLDOWN_SHORT, reason)
        with _lock:
            _fail_streak[service] = 0


def _mark_ok(service: str):
    with _lock:
        _skip_until[service] = 0.0
        _fail_streak[service] = 0


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
    if not _available("elevenlabs"):
        return False

    # Kanal ayarındaki boş değerler (örn. voice_id "") varsayılanı ezmesin
    vc = {**_default_voice_config(),
          **{k: v for k, v in (voice_config or {}).items()
             if v not in (None, "")}}

    import httpx
    from elevenlabs import ElevenLabs, save

    for attempt in (1, 2):
        try:
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
            _mark_ok("elevenlabs")
            log.info(f"    ✅ ElevenLabs ({vc['voice_id'][:8]}…): {os.path.basename(out_path)}")
            return True
        except Exception as e:
            err_msg = str(e)
            log.warning(f"    ⚠ ElevenLabs: {err_msg[:150]}")
            status = getattr(e, "status_code", None)
            lower = err_msg.lower()
            if status in (401, 402, 403) or any(
                    x in lower for x in ("quota", "billing", "unauthorized",
                                         "credits")):
                # Hesap düzeyinde sorun: her segmentte tekrar denemeye değmez
                _cool_down("elevenlabs", _COOLDOWN_LONG, err_msg)
                return False
            if status == 429 or status is None or status >= 500:
                # Geçici (aşırı yük / sunucu / ağ): bir kez daha dene ki
                # videonun ortasında ses başka servise geçmesin
                if attempt == 1:
                    time.sleep(2)
                    continue
                _transient_failure("elevenlabs", err_msg)
            # Diğer 4xx (örn. bir kanalın geçersiz voice_id'si) sadece bu
            # isteğe özgü; diğer kanalları etkilememesi için bekleme yok
            return False
    return False


def _tts_edge(text: str, out_path: str) -> bool:
    """Microsoft Edge TTS — ücretsiz fallback."""
    if not _available("edge"):
        return False
    try:
        async def _run():
            import edge_tts
            voice = os.environ.get("EDGE_TTS_VOICE", "tr-TR-EmelNeural")
            comm = edge_tts.Communicate(text=text, voice=voice, rate="+3%")
            await comm.save(out_path)

        asyncio.run(_run())
        if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
            _mark_ok("edge")
            log.info(f"    ✅ Edge TTS: {os.path.basename(out_path)}")
            return True
        return False
    except Exception as e:
        log.warning(f"    ⚠ Edge TTS: {str(e)[:100]}")
        _transient_failure("edge", str(e))
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
    with _lock:
        for k in _skip_until:
            _skip_until[k] = 0.0
            _fail_streak[k] = 0
