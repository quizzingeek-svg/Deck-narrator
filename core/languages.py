"""Supported narration languages with curated, natural-sounding default voices.

Each entry: code (ISO-639-1, used by Whisper / translators), locale, the best-sounding edge-tts
voices (female, male), the spoken "move to the next slide" cue, and voice-command keywords.
Defaults prefer Microsoft's newest *Multilingual* / expressive neural voices where they exist,
because they sound the least robotic.
"""
from __future__ import annotations

from typing import Dict, List

# name: (iso, edge locale, female voice, male voice, cue, next-words, prev-words, repeat-words, gtts code)
_RAW = [
    ("English (US)", "en", "en-US", "en-US-AvaMultilingualNeural", "en-US-AndrewMultilingualNeural",
     "Please move to the next slide.", ["next", "next slide", "continue", "go on", "move on"],
     ["previous", "go back", "back"], ["repeat", "again", "say that again"], "en"),
    ("English (UK)", "en", "en-GB", "en-GB-SoniaNeural", "en-GB-RyanNeural",
     "Please move on to the next slide.", ["next", "next slide", "continue", "go on", "move on"],
     ["previous", "go back", "back"], ["repeat", "again"], "en"),
    ("English (India)", "en", "en-IN", "en-IN-NeerjaExpressiveNeural", "en-IN-PrabhatNeural",
     "Please move to the next slide.", ["next", "next slide", "continue", "go on", "move on"],
     ["previous", "go back", "back"], ["repeat", "again"], "en"),
    ("Hindi", "hi", "hi-IN", "hi-IN-SwaraNeural", "hi-IN-MadhurNeural",
     "कृपया अगली स्लाइड पर जाइए।", ["अगला", "अगली", "आगे", "नेक्स्ट", "next"],
     ["पिछला", "पिछली", "वापस", "previous"], ["दोबारा", "फिर से", "repeat"], "hi"),
    ("Spanish (Spain)", "es", "es-ES", "es-ES-XimenaNeural", "es-ES-AlvaroNeural",
     "Por favor, pasa a la siguiente diapositiva.", ["siguiente", "adelante", "continúa", "continua", "next"],
     ["anterior", "atrás", "atras"], ["repite", "otra vez"], "es"),
    ("Spanish (Mexico / LatAm)", "es", "es-MX", "es-MX-DaliaNeural", "es-MX-JorgeNeural",
     "Por favor, pasa a la siguiente diapositiva.", ["siguiente", "adelante", "continúa", "continua", "next"],
     ["anterior", "atrás", "atras"], ["repite", "otra vez"], "es"),
    ("French", "fr", "fr-FR", "fr-FR-VivienneMultilingualNeural", "fr-FR-RemyMultilingualNeural",
     "Merci de passer à la diapositive suivante.", ["suivant", "suivante", "continue", "continuer", "next"],
     ["précédent", "précédente", "retour"], ["répète", "encore"], "fr"),
    ("German", "de", "de-DE", "de-DE-SeraphinaMultilingualNeural", "de-DE-FlorianMultilingualNeural",
     "Bitte wechseln Sie zur nächsten Folie.", ["weiter", "nächste", "nächster", "next"],
     ["zurück", "vorherige"], ["wiederholen", "nochmal", "noch mal"], "de"),
    ("Portuguese (Brazil)", "pt", "pt-BR", "pt-BR-ThalitaMultilingualNeural", "pt-BR-AntonioNeural",
     "Por favor, avance para o próximo slide.", ["próximo", "proximo", "avançar", "avancar", "seguinte", "next"],
     ["anterior", "voltar"], ["repetir", "de novo"], "pt"),
    ("Portuguese (Portugal)", "pt", "pt-PT", "pt-PT-RaquelNeural", "pt-PT-DuarteNeural",
     "Por favor, avance para o diapositivo seguinte.", ["próximo", "seguinte", "avançar", "next"],
     ["anterior", "voltar"], ["repetir", "outra vez"], "pt"),
    ("Arabic", "ar", "ar-SA", "ar-SA-ZariyahNeural", "ar-SA-HamedNeural",
     "من فضلك انتقل إلى الشريحة التالية.", ["التالي", "التالية", "تابع", "next"],
     ["السابق", "السابقة", "رجوع"], ["كرر", "أعد"], "ar"),
    ("Arabic (Egypt)", "ar", "ar-EG", "ar-EG-SalmaNeural", "ar-EG-ShakirNeural",
     "من فضلك انتقل إلى الشريحة التالية.", ["التالي", "التالية", "تابع", "next"],
     ["السابق", "رجوع"], ["كرر"], "ar"),
    ("Chinese (Mandarin, Simplified)", "zh", "zh-CN", "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural",
     "请切换到下一张幻灯片。", ["下一张", "下一页", "下一个", "继续", "next"],
     ["上一张", "上一页", "返回"], ["重复", "再说一遍"], "zh-CN"),
    ("Chinese (Taiwan, Traditional)", "zh", "zh-TW", "zh-TW-HsiaoChenNeural", "zh-TW-YunJheNeural",
     "請切換到下一張投影片。", ["下一張", "下一頁", "繼續", "next"],
     ["上一張", "上一頁"], ["重複"], "zh-TW"),
    ("Cantonese (Hong Kong)", "zh", "zh-HK", "zh-HK-HiuMaanNeural", "zh-HK-WanLungNeural",
     "請轉去下一張投影片。", ["下一張", "下一頁", "繼續", "next"], ["上一張"], ["重複"], "zh-TW"),
    ("Japanese", "ja", "ja-JP", "ja-JP-NanamiNeural", "ja-JP-KeitaNeural",
     "次のスライドに進んでください。", ["次", "つぎ", "ネクスト", "進んで", "next"],
     ["前", "戻って", "もどって"], ["もう一度", "繰り返"], "ja"),
    ("Korean", "ko", "ko-KR", "ko-KR-SunHiNeural", "ko-KR-HyunsuMultilingualNeural",
     "다음 슬라이드로 넘어가 주세요.", ["다음", "넥스트", "계속", "next"],
     ["이전", "뒤로"], ["다시", "반복"], "ko"),
    ("Russian", "ru", "ru-RU", "ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural",
     "Пожалуйста, переходите к следующему слайду.", ["дальше", "следующий", "следующая", "далее", "next"],
     ["назад", "предыдущий"], ["повтори", "ещё раз", "еще раз"], "ru"),
    ("Italian", "it", "it-IT", "it-IT-IsabellaNeural", "it-IT-GiuseppeMultilingualNeural",
     "Per favore, passa alla slide successiva.", ["avanti", "successiva", "successivo", "prossima", "next"],
     ["indietro", "precedente"], ["ripeti", "di nuovo"], "it"),
    ("Turkish", "tr", "tr-TR", "tr-TR-EmelNeural", "tr-TR-AhmetNeural",
     "Lütfen bir sonraki slayta geçin.", ["sonraki", "ileri", "devam", "next"],
     ["önceki", "geri"], ["tekrar"], "tr"),
    ("Indonesian", "id", "id-ID", "id-ID-GadisNeural", "id-ID-ArdiNeural",
     "Silakan lanjut ke slide berikutnya.", ["berikutnya", "lanjut", "selanjutnya", "next"],
     ["sebelumnya", "kembali"], ["ulangi"], "id"),
    ("Malay", "ms", "ms-MY", "ms-MY-YasminNeural", "ms-MY-OsmanNeural",
     "Sila beralih ke slaid seterusnya.", ["seterusnya", "berikutnya", "teruskan", "next"],
     ["sebelumnya", "kembali"], ["ulang"], "ms"),
    ("Vietnamese", "vi", "vi-VN", "vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural",
     "Vui lòng chuyển sang trang chiếu tiếp theo.", ["tiếp theo", "tiếp", "next"],
     ["trước", "quay lại"], ["lặp lại", "nhắc lại"], "vi"),
    ("Thai", "th", "th-TH", "th-TH-PremwadeeNeural", "th-TH-NiwatNeural",
     "กรุณาเปลี่ยนไปสไลด์ถัดไป", ["ถัดไป", "ต่อไป", "next"], ["ก่อนหน้า", "ย้อนกลับ"], ["พูดอีกครั้ง", "ซ้ำ"], "th"),
    ("Filipino", "tl", "fil-PH", "fil-PH-BlessicaNeural", "fil-PH-AngeloNeural",
     "Pakilipat po sa susunod na slide.", ["susunod", "sunod", "next"], ["nakaraan", "bumalik"], ["ulitin"], "tl"),
    ("Bengali", "bn", "bn-IN", "bn-IN-TanishaaNeural", "bn-IN-BashkarNeural",
     "অনুগ্রহ করে পরের স্লাইডে যান।", ["পরের", "পরবর্তী", "এগিয়ে", "নেক্সট", "next"],
     ["আগের", "পিছনে"], ["আবার"], "bn"),
    ("Bengali (Bangladesh)", "bn", "bn-BD", "bn-BD-NabanitaNeural", "bn-BD-PradeepNeural",
     "অনুগ্রহ করে পরের স্লাইডে যান।", ["পরের", "পরবর্তী", "নেক্সট", "next"], ["আগের"], ["আবার"], "bn"),
    ("Tamil", "ta", "ta-IN", "ta-IN-PallaviNeural", "ta-IN-ValluvarNeural",
     "தயவுசெய்து அடுத்த ஸ்லைடுக்குச் செல்லுங்கள்.", ["அடுத்த", "அடுத்தது", "நெக்ஸ்ட்", "next"],
     ["முந்தைய", "பின்"], ["மீண்டும்"], "ta"),
    ("Telugu", "te", "te-IN", "te-IN-ShrutiNeural", "te-IN-MohanNeural",
     "దయచేసి తదుపరి స్లైడ్‌కు వెళ్ళండి.", ["తదుపరి", "తర్వాత", "నెక్స్ట్", "next"],
     ["మునుపటి", "వెనక్కి"], ["మళ్ళీ"], "te"),
    ("Marathi", "mr", "mr-IN", "mr-IN-AarohiNeural", "mr-IN-ManoharNeural",
     "कृपया पुढील स्लाइडवर जा.", ["पुढील", "पुढे", "नेक्स्ट", "next"], ["मागील", "मागे"], ["पुन्हा"], "mr"),
    ("Gujarati", "gu", "gu-IN", "gu-IN-DhwaniNeural", "gu-IN-NiranjanNeural",
     "કૃપા કરીને આગલી સ્લાઇડ પર જાઓ.", ["આગળ", "આગલી", "નેક્સ્ટ", "next"], ["પાછળ", "પાછલી"], ["ફરીથી"], "gu"),
    ("Kannada", "kn", "kn-IN", "kn-IN-SapnaNeural", "kn-IN-GaganNeural",
     "ದಯವಿಟ್ಟು ಮುಂದಿನ ಸ್ಲೈಡ್‌ಗೆ ಹೋಗಿ.", ["ಮುಂದಿನ", "ಮುಂದೆ", "ನೆಕ್ಸ್ಟ್", "next"], ["ಹಿಂದಿನ", "ಹಿಂದೆ"], ["ಮತ್ತೆ"], "kn"),
    ("Malayalam", "ml", "ml-IN", "ml-IN-SobhanaNeural", "ml-IN-MidhunNeural",
     "ദയവായി അടുത്ത സ്ലൈഡിലേക്ക് പോകൂ.", ["അടുത്ത", "അടുത്തത്", "നെക്സ്റ്റ്", "next"], ["മുമ്പത്തെ", "പിന്നിലേക്ക്"], ["വീണ്ടും"], "ml"),
    ("Punjabi", "pa", "", "", "",
     "ਕਿਰਪਾ ਕਰਕੇ ਅਗਲੀ ਸਲਾਈਡ 'ਤੇ ਜਾਓ।", ["ਅਗਲੀ", "ਅਗਲਾ", "ਅੱਗੇ", "ਨੈਕਸਟ", "next"], ["ਪਿਛਲੀ", "ਪਿੱਛੇ"], ["ਦੁਬਾਰਾ"], "pa"),
    ("Urdu", "ur", "ur-PK", "ur-PK-UzmaNeural", "ur-PK-AsadNeural",
     "براہ کرم اگلی سلائیڈ پر جائیں۔", ["اگلی", "اگلا", "آگے", "نیکسٹ", "next"], ["پچھلی", "پیچھے"], ["دوبارہ"], "ur"),
    ("Nepali", "ne", "ne-NP", "ne-NP-HemkalaNeural", "ne-NP-SagarNeural",
     "कृपया अर्को स्लाइडमा जानुहोस्।", ["अर्को", "अगाडि", "नेक्स्ट", "next"], ["अघिल्लो", "पछाडि"], ["फेरि"], "ne"),
    ("Sinhala", "si", "si-LK", "si-LK-ThiliniNeural", "si-LK-SameeraNeural",
     "කරුණාකර ඊළඟ ස්ලයිඩයට යන්න.", ["ඊළඟ", "ඉදිරියට", "next"], ["පෙර", "ආපසු"], ["නැවත"], "si"),
    ("Dutch", "nl", "nl-NL", "nl-NL-FennaNeural", "nl-NL-MaartenNeural",
     "Ga alstublieft naar de volgende dia.", ["volgende", "verder", "door", "next"], ["vorige", "terug"], ["herhaal", "nog een keer"], "nl"),
    ("Polish", "pl", "pl-PL", "pl-PL-ZofiaNeural", "pl-PL-MarekNeural",
     "Proszę przejść do następnego slajdu.", ["dalej", "następny", "następna", "next"], ["wstecz", "poprzedni"], ["powtórz"], "pl"),
    ("Swedish", "sv", "sv-SE", "sv-SE-SofieNeural", "sv-SE-MattiasNeural",
     "Gå vidare till nästa bild, tack.", ["nästa", "vidare", "fortsätt", "next"], ["föregående", "tillbaka"], ["upprepa", "igen"], "sv"),
    ("Danish", "da", "da-DK", "da-DK-ChristelNeural", "da-DK-JeppeNeural",
     "Gå venligst videre til næste dias.", ["næste", "videre", "fortsæt", "next"], ["forrige", "tilbage"], ["gentag"], "da"),
    ("Norwegian", "no", "nb-NO", "nb-NO-PernilleNeural", "nb-NO-FinnNeural",
     "Gå videre til neste lysbilde.", ["neste", "videre", "fortsett", "next"], ["forrige", "tilbake"], ["gjenta"], "no"),
    ("Finnish", "fi", "fi-FI", "fi-FI-NooraNeural", "fi-FI-HarriNeural",
     "Siirry seuraavaan diaan.", ["seuraava", "eteenpäin", "jatka", "next"], ["edellinen", "takaisin"], ["toista"], "fi"),
    ("Ukrainian", "uk", "uk-UA", "uk-UA-PolinaNeural", "uk-UA-OstapNeural",
     "Будь ласка, перейдіть до наступного слайда.", ["далі", "наступний", "наступна", "next"], ["назад", "попередній"], ["повтори"], "uk"),
    ("Hebrew", "he", "he-IL", "he-IL-HilaNeural", "he-IL-AvriNeural",
     "נא לעבור לשקופית הבאה.", ["הבא", "הבאה", "המשך", "next"], ["הקודם", "הקודמת", "אחורה"], ["חזור", "שוב"], "iw"),
    ("Persian", "fa", "fa-IR", "fa-IR-DilaraNeural", "fa-IR-FaridNeural",
     "لطفاً به اسلاید بعدی بروید.", ["بعدی", "ادامه", "next"], ["قبلی", "برگرد"], ["تکرار"], "fa"),
    ("Swahili", "sw", "sw-KE", "sw-KE-ZuriNeural", "sw-KE-RafikiNeural",
     "Tafadhali nenda kwenye slaidi inayofuata.", ["inayofuata", "endelea", "mbele", "next"], ["iliyopita", "rudi"], ["rudia"], "sw"),
    ("Amharic", "am", "am-ET", "am-ET-MekdesNeural", "am-ET-AmehaNeural",
     "እባክዎ ወደ ቀጣዩ ስላይድ ይሂዱ።", ["ቀጣይ", "ቀጣዩ", "next"], ["ቀዳሚ", "ተመለስ"], ["ድገም"], "am"),
    ("Zulu", "zu", "zu-ZA", "zu-ZA-ThandoNeural", "zu-ZA-ThembaNeural",
     "Sicela udlulele kusilayidi olandelayo.", ["olandelayo", "qhubeka", "next"], ["edlule", "buyela"], ["phinda"], "zu"),
    ("Afrikaans", "af", "af-ZA", "af-ZA-AdriNeural", "af-ZA-WillemNeural",
     "Gaan asseblief na die volgende skyfie.", ["volgende", "gaan aan", "next"], ["vorige", "terug"], ["herhaal"], "af"),
    ("Greek", "el", "el-GR", "el-GR-AthinaNeural", "el-GR-NestorasNeural",
     "Παρακαλώ προχωρήστε στην επόμενη διαφάνεια.", ["επόμενη", "επόμενο", "συνέχεια", "next"], ["προηγούμενη", "πίσω"], ["ξανά", "επανάληψη"], "el"),
    ("Czech", "cs", "cs-CZ", "cs-CZ-VlastaNeural", "cs-CZ-AntoninNeural",
     "Přejděte prosím na další snímek.", ["další", "dál", "pokračuj", "next"], ["předchozí", "zpět"], ["zopakuj", "znovu"], "cs"),
    ("Slovak", "sk", "sk-SK", "sk-SK-ViktoriaNeural", "sk-SK-LukasNeural",
     "Prejdite, prosím, na ďalšiu snímku.", ["ďalej", "ďalšia", "ďalší", "next"], ["predchádzajúca", "späť"], ["zopakuj"], "sk"),
    ("Romanian", "ro", "ro-RO", "ro-RO-AlinaNeural", "ro-RO-EmilNeural",
     "Vă rog să treceți la următorul diapozitiv.", ["următorul", "următoarea", "înainte", "next"], ["anterior", "înapoi"], ["repetă"], "ro"),
    ("Hungarian", "hu", "hu-HU", "hu-HU-NoemiNeural", "hu-HU-TamasNeural",
     "Kérem, lépjen a következő diára.", ["következő", "tovább", "next"], ["előző", "vissza"], ["ismételd", "újra"], "hu"),
    ("Bulgarian", "bg", "bg-BG", "bg-BG-KalinaNeural", "bg-BG-BorislavNeural",
     "Моля, преминете към следващия слайд.", ["следващ", "следващия", "напред", "next"], ["предишен", "назад"], ["повтори"], "bg"),
    ("Croatian", "hr", "hr-HR", "hr-HR-GabrijelaNeural", "hr-HR-SreckoNeural",
     "Molim prijeđite na sljedeći slajd.", ["sljedeći", "dalje", "next"], ["prethodni", "natrag"], ["ponovi"], "hr"),
    ("Serbian", "sr", "sr-RS", "sr-RS-SophieNeural", "sr-RS-NicholasNeural",
     "Молим пређите на следећи слајд.", ["следећи", "даље", "sledeći", "dalje", "next"], ["претходни", "назад"], ["понови"], "sr"),
    ("Kazakh", "kk", "kk-KZ", "kk-KZ-AigulNeural", "kk-KZ-DauletNeural",
     "Келесі слайдқа өтіңіз.", ["келесі", "әрі қарай", "next"], ["алдыңғы", "артқа"], ["қайтала"], "kk"),
    ("Uzbek", "uz", "uz-UZ", "uz-UZ-MadinaNeural", "uz-UZ-SardorNeural",
     "Iltimos, keyingi slaydga o'ting.", ["keyingi", "davom", "next"], ["oldingi", "orqaga"], ["takrorla"], "uz"),
    ("Burmese", "my", "my-MM", "my-MM-NilarNeural", "my-MM-ThihaNeural",
     "ကျေးဇူးပြု၍ နောက်ဆလိုက်သို့ ကူးပါ။", ["နောက်တစ်ခု", "ဆက်", "next"], ["ယခင်"], ["ထပ်"], "my"),
    ("Khmer", "km", "km-KH", "km-KH-SreymomNeural", "km-KH-PisethNeural",
     "សូមប្តូរទៅស្លាយបន្ទាប់។", ["បន្ទាប់", "next"], ["មុន"], ["ម្តងទៀត"], "km"),
]

LANGUAGES: Dict[str, dict] = {}
for (name, iso, loc, fem, male, cue, nxt, prv, rep, gt) in _RAW:
    LANGUAGES[name] = {"name": name, "iso": iso, "locale": loc, "female": fem, "male": male,
                       "cue": cue, "next": nxt, "prev": prv, "repeat": rep, "gtts": gt}

# Voices that can speak almost any language naturally (they auto-detect the text language).
MULTILINGUAL_VOICES = [
    "en-US-AvaMultilingualNeural", "en-US-AndrewMultilingualNeural", "en-US-EmmaMultilingualNeural",
    "en-US-BrianMultilingualNeural", "en-AU-WilliamMultilingualNeural", "fr-FR-VivienneMultilingualNeural",
    "fr-FR-RemyMultilingualNeural", "de-DE-SeraphinaMultilingualNeural", "de-DE-FlorianMultilingualNeural",
    "it-IT-GiuseppeMultilingualNeural", "ko-KR-HyunsuMultilingualNeural", "pt-BR-ThalitaMultilingualNeural",
]


def language_names() -> List[str]:
    return list(LANGUAGES.keys())


def default_voice(lang: str, gender: str = "Female") -> str:
    L = LANGUAGES[lang]
    v = L["female"] if gender.lower().startswith("f") else L["male"]
    return v or L["female"] or L["male"]


def voices_for(lang: str, all_voices: List[dict] | None = None) -> List[str]:
    """Curated defaults first, then every other edge-tts voice for the same language, then multilingual voices."""
    L = LANGUAGES[lang]
    out: List[str] = [v for v in (L["female"], L["male"]) if v]
    if all_voices:
        prefix = L["iso"] if L["iso"] not in ("no", "tl") else {"no": "nb", "tl": "fil"}[L["iso"]]
        same_loc = [v["ShortName"] for v in all_voices if v["Locale"] == L["locale"]]
        same_lang = [v["ShortName"] for v in all_voices if v["Locale"].split("-")[0] == prefix]
        for v in same_loc + same_lang:
            if v not in out:
                out.append(v)
    for v in MULTILINGUAL_VOICES:
        if v not in out:
            out.append(v)
    return out


# Romanised forms Whisper often outputs for Indic / Urdu speech (it may transliterate instead of using native script)
_ROMAN = {
    "Hindi": (["agli", "agla", "aage", "aagey", "age badho"], ["pichli", "pichla", "peeche", "wapas"], ["dobara", "phir se"]),
    "Urdu": (["agli", "agla", "aage"], ["pichli", "peeche", "wapas"], ["dobara"]),
    "Punjabi": (["agli", "agla", "agge"], ["pichli", "pichhe"], ["dubara"]),
    "Marathi": (["pudhil", "pudhe"], ["magil", "mage"], ["punha"]),
    "Gujarati": (["aagal", "aagli"], ["pachhal", "pachhli"], ["farithi"]),
    "Bengali": (["porer", "porobor", "egiye"], ["ager", "pichone"], ["abar"]),
    "Tamil": (["adutha", "aduththa", "aduthathu"], ["munthaya", "pin"], ["meendum"]),
    "Telugu": (["tadupari", "tarvata"], ["munupati", "venakki"], ["malli"]),
    "Kannada": (["mundina", "munde"], ["hindina", "hinde"], ["matte"]),
    "Malayalam": (["adutha", "aduthathu"], ["munpathe"], ["veendum"]),
    "Nepali": (["arko", "agadi"], ["aghillo", "pachadi"], ["feri"]),
}
for _n, (_nx, _pv, _rp) in _ROMAN.items():
    LANGUAGES[_n]["next"] += _nx; LANGUAGES[_n]["prev"] += _pv; LANGUAGES[_n]["repeat"] += _rp
