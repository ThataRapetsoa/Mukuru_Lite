"""Minimal bilingual strings (English / isiZulu) for the USSD flow."""
from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
	"welcome": {
		"en": "Hi, welcome to Mukuru!\n\n1. I'm new\n2. I'm already a Mukuru customer",
		"zu": "Sawubona, siyakwamukela kwaMukuru!\n\n1. Ngingumuntu omusha\n2. Sengingukhasimende weMukuru",
	},
	"choose_language": {
		"en": "Choose language / Khetha ulimi:\n\n1. English\n2. isiZulu",
		"zu": "Choose language / Khetha ulimi:\n\n1. English\n2. isiZulu",
	},
	"send_money": {
		"en": "SEND MONEY\n\n1. Send Money Now\n2. Planned Payment\n3. My Payments\n0. Home",
		"zu": "THUMELA IMALI\n\n1. Thumela Imali Manje\n2. Indlela Eklanyiwe\n3. Izinkokhelo Zami\n0. Ikhaya",
	},
	"cellphone": {"en": "Cellphone Number:", "zu": "Inombolo Yekholi:"},
	"pin": {"en": "PIN:", "zu": "I-PIN:"},
	"first_name": {"en": "First Name:", "zu": "Igama:"},
	"surname": {"en": "Surname:", "zu": "Isibongo:"},
	"dob": {"en": "Date of Birth (DD.MM.YYYY):", "zu": "Usuku Lokuzalwa (DD.MM.YYYY):"},
	"home_language": {
		"en": "Home Language:\n1. English\n2. isiZulu\n3. isiXhosa\n4. Other",
		"zu": "Ulimi Lwasekhaya:\n1. English\n2. isiZulu\n3. isiXhosa\n4. Okunye",
	},
	"create_pin": {"en": "Create 4-digit PIN:", "zu": "Dala i-PIN enezinombolo ezi-4:"},
	"signup_thanks": {
		"en": "Thanks for signing up!\n\nWelcome to Mukuru, {name}.\n\n1. Send money now\n0. Home",
		"zu": "Sibonga ngokubhalisa!\n\nSiyakwamukela kwaMukuru, {name}.\n\n1. Thumela imali manje\n0. Ikhaya",
	},
	"main_menu": {
		"en": "Hi {name}, welcome to Mukuru!\n\n1. Send money now\n2. Mukuru Card\n3. Buy/Pay\n4. Insurance\n5. Save in Dollars (NEW)\n6. Loans\n7. Next\n0. Exit",
		"zu": "Sawubona {name}, siyakwamukela kwaMukuru!\n\n1. Thumela imali manje\n2. Ikhadi leMukuru\n3. Thenga/Khokha\n4. Umshwalense\n5. Longela NgeDollar (OKUSHAK)\n6. Imali Ebolekiwe\n7. Okulandelayo\n0. Phuma",
	},
	"not_demo": {"en": "This feature is not part of this demo.", "zu": "Lesi sici asisemo uzweni lwethu."},
	"try_again": {"en": "1. Try Again\n2. Back", "zu": "1. Zama Futhi\n2. Emuva"},
}


def tr(lang: str, key: str, **kwargs) -> str:
	entry = STRINGS.get(key, {})
	text = entry.get(lang, entry.get("en", key))
	return text.format(**kwargs) if kwargs else text
