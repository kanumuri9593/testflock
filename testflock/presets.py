"""Built-in device, network and language presets.

Every preset is plain data, so a team can add its own in qa.yml under
`presets:` without touching code.
"""

# Web viewports (CSS pixels). `mobile` and `touch` switch Chromium into phone mode.
WEB_DEVICES = {
    "iphone-se": {"width": 375, "height": 667, "dpr": 2, "mobile": True, "touch": True,
                  "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"},
    "iphone-16": {"width": 393, "height": 852, "dpr": 3, "mobile": True, "touch": True,
                  "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"},
    "iphone-16-pro-max": {"width": 440, "height": 956, "dpr": 3, "mobile": True, "touch": True,
                          "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"},
    "pixel-5": {"width": 393, "height": 851, "dpr": 2.75, "mobile": True, "touch": True,
                "ua": "Mozilla/5.0 (Linux; Android 14; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"},
    "pixel-8": {"width": 412, "height": 915, "dpr": 2.625, "mobile": True, "touch": True,
                "ua": "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"},
    "galaxy-s24": {"width": 360, "height": 780, "dpr": 3, "mobile": True, "touch": True,
                   "ua": "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"},
    "small-android": {"width": 320, "height": 640, "dpr": 2, "mobile": True, "touch": True,
                      "ua": "Mozilla/5.0 (Linux; Android 11; Nexus 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"},
    "ipad-mini": {"width": 744, "height": 1133, "dpr": 2, "mobile": True, "touch": True,
                  "ua": "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"},
    "ipad-pro-13": {"width": 1032, "height": 1376, "dpr": 2, "mobile": True, "touch": True,
                    "ua": "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"},
    "laptop": {"width": 1366, "height": 768, "dpr": 1, "mobile": False, "touch": False},
    "desktop": {"width": 1440, "height": 900, "dpr": 2, "mobile": False, "touch": False},
}

# Android emulator hardware profiles (`avdmanager list device`) and API levels.
ANDROID_DEVICES = {
    "pixel-8": {"profile": "pixel_8", "api": 35},
    "pixel-5": {"profile": "pixel_5", "api": 34},
    "small-android": {"profile": "Nexus 5", "api": 30},
    "pixel-tablet": {"profile": "pixel_tablet", "api": 34},
}

# iOS Simulator device types (`xcrun simctl list devicetypes`).
IOS_DEVICES = {
    "iphone-se": {"type": "iPhone SE (3rd generation)"},
    "iphone-16": {"type": "iPhone 16"},
    "iphone-16-pro-max": {"type": "iPhone 16 Pro Max"},
    "iphone-17": {"type": "iPhone 17"},
    "ipad-mini": {"type": "iPad mini (A17 Pro)"},
    "ipad-pro-13": {"type": "iPad Pro 13-inch (M4)"},
}

# Network profiles. Throughput in kilobits per second, latency in milliseconds.
NETWORKS = {
    "online": {"offline": False},
    "offline": {"offline": True},
    "wifi": {"down_kbps": 30000, "up_kbps": 15000, "latency_ms": 2, "android": "full"},
    "4g": {"down_kbps": 9000, "up_kbps": 9000, "latency_ms": 85, "android": "lte"},
    "fast-3g": {"down_kbps": 1600, "up_kbps": 750, "latency_ms": 150, "android": "umts"},
    "slow-3g": {"down_kbps": 400, "up_kbps": 400, "latency_ms": 400, "android": "umts"},
    "2g": {"down_kbps": 50, "up_kbps": 20, "latency_ms": 650, "android": "gsm"},
    "flaky": {"down_kbps": 800, "up_kbps": 400, "latency_ms": 900, "android": "edge"},
}

# Text sizes. Web scales the root font size, Android sets font_scale,
# iOS maps to a Dynamic Type content size category.
TEXT_SIZES = {
    "small": {"scale": 0.85, "ios": "small"},
    "default": {"scale": 1.0, "ios": "large"},
    "large": {"scale": 1.3, "ios": "extra-extra-large"},
    "largest": {"scale": 2.0, "ios": "accessibility-extra-extra-extra-large"},
}

# Timezone and rough geolocation that match each language, so dates,
# currencies and maps look like a real user's phone.
LOCALES = {
    "en-US": {"tz": "America/New_York", "geo": [40.7128, -74.0060]},
    "en-GB": {"tz": "Europe/London", "geo": [51.5072, -0.1276]},
    "en-IN": {"tz": "Asia/Kolkata", "geo": [17.3850, 78.4867]},
    "es-ES": {"tz": "Europe/Madrid", "geo": [40.4168, -3.7038]},
    "es-MX": {"tz": "America/Mexico_City", "geo": [19.4326, -99.1332]},
    "fr-FR": {"tz": "Europe/Paris", "geo": [48.8566, 2.3522]},
    "de-DE": {"tz": "Europe/Berlin", "geo": [52.5200, 13.4050]},
    "it-IT": {"tz": "Europe/Rome", "geo": [41.9028, 12.4964]},
    "pt-BR": {"tz": "America/Sao_Paulo", "geo": [-23.5505, -46.6333]},
    "ja-JP": {"tz": "Asia/Tokyo", "geo": [35.6762, 139.6503]},
    "ko-KR": {"tz": "Asia/Seoul", "geo": [37.5665, 126.9780]},
    "zh-CN": {"tz": "Asia/Shanghai", "geo": [31.2304, 121.4737]},
    "hi-IN": {"tz": "Asia/Kolkata", "geo": [28.6139, 77.2090]},
    "te-IN": {"tz": "Asia/Kolkata", "geo": [17.3850, 78.4867]},
    "ar-SA": {"tz": "Asia/Riyadh", "geo": [24.7136, 46.6753]},
}

# Labels the no-AI crawler never taps, so a run never deletes data,
# signs out or spends money. Extend it in qa.yml with `crawl.avoid`.
DEFAULT_AVOID = [
    "delete", "remove", "erase", "reset", "sign out", "log out", "logout",
    "buy", "purchase", "subscribe", "pay", "checkout", "send", "report",
    "borrar", "eliminar", "supprimer", "löschen",
]
