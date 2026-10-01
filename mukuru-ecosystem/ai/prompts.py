"""Localized reply templates.

Three languages means three sets of strings, and a missing key is a crash in
production. Every table is therefore complete, and :mod:`test_prompts` walks
all of them.

Templates are ``str.format`` strings: ``{amount}``, ``{recipient}`` and so on.
Anything user-supplied is passed as a format argument, never interpolated into
the template, so a recipient named ``{}`` cannot break the reply.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from ai.languages import Language

#: Where a fee goes, in words, per language. Kept short because it is read out
#: loud before every transfer.
TEMPLATES: Mapping[Language, Mapping[str, str]] = {
    Language.EN: {
        "greeting": "Hi. I can send money, check a transfer, or tell you the exchange rate. What would you like to do?",
        "help": "I can help you send money, check a transfer, get an exchange rate, work out the fee, set up a repeating payment, or show your history.",
        "unknown": "Sorry, I did not catch that. You can ask me to send money, check a transfer, or get an exchange rate.",
        "ask_amount": "How much would you like to send?",
        "ask_recipient": "Who would you like to send it to?",
        "ask_country": "Which country is the money going to?",
        "ask_when": "When would you like this to happen?",
        "ask_reference": "Which transfer would you like me to look up? You can give me the reference number.",
        "unclear_intent": "I want to be sure I have that right. Do you want me to send money, check a transfer, or set up a repeating payment?",
        "quote": "You are sending {send_amount}. The fee is {fee}, so {total} leaves your account. {recipient} receives {receive_amount} at a rate of {rate}. Send it?",
        "quote_words": "You are sending {send_amount}. The fee is {fee}, so {total} comes out of your wallet. {recipient} gets {receive_amount}.",
        "sent": "Done. {amount} is on its way to {recipient}. Your reference is {reference}. You can track it at any time.",
        "scheduled": "Set up. I will send {amount} to {recipient} on {when}. Reference {reference}.",
        "cancelled": "I have cancelled that repeating payment.",
        "status": "Transfer {reference} is {status}. {detail}",
        "status_unknown": "I could not find a transfer with reference {reference}. Please check the number, or ask me to show your recent transfers.",
        "history": "Here are your recent transfers: {items}",
        "history_empty": "You have no transfers yet.",
        "rate": "One {send_currency} is {rate} {receive_currency} today. This rate can move, so the final amount is confirmed when you send.",
        "calculated": "For {amount}, the fee is {fee} and {recipient} would receive {receive_amount}.",
        "balance": "You have {balance} available.",
        "confirm_prompt": "Please confirm to continue.",
        "confirm_cancel": "Shall I cancel your repeating payment of {amount} to {recipient}?",
        "declined": "No problem, I have cancelled that.",
        "too_low": "The smallest transfer I can send is {minimum}.",
        "too_high": "The largest transfer I can send in one go is {maximum}.",
        "insufficient_funds": "You have {balance} available, which is not enough for this transfer.",
        "backend_down": "I cannot reach Mukuru right now. Please try again in a moment, and nothing has been sent.",
        "expired": "That confirmation has expired. Let us start again.",
        "not_enabled": "That is not something I can do yet.",
        "recipient_list": "Who would you like to send it to? You can say a name, or tell me a phone number.",
        "transaction_item": "{reference}, {amount} to {recipient}, {status}",
        "listening": "I am listening.",
        "speaking_error": "I could not read that out, but here it is in writing.",
        "heard": "You said: {text}",
    },
    Language.ZU: {
        "greeting": "Sawubona. Ngingakusiza ukuthumela imali, ukuhlola isicelo, noma ukunika inga lokushintshanwa. Ufuna ukwenzani?",
        "help": "Ngingakusiza ukuthumela imali, ukuhlola isicelo, ukunika inga lokushintshanwa, ukubala ikupheula, ukuhlelela ukhokhelo olujulile, noma ukubonisa umlando wakho.",
        "unknown": "Angizwanga kahle. Ungangitshela ukuthumela imali, ukuhlola isicelo, noma ukunika inga lokushintshanwa.",
        "ask_amount": "Ungathumela kangakani?",
        "ask_recipient": "Ungathumela komani?",
        "ask_country": "Imali iyoshuna kuphi?",
        "ask_when": "Ngingakwenza nini?",
        "ask_reference": "Yisiphi isicelo ofuna ngisibheke? Unganginika inombolo yesithenzo.",
        "unclear_intent": "Ngifuna uqinisekise ukuthi kulungile. Unginceda ukuthumela imali, ukuhlola isicelo, noma ukuhlelela ukhokhelo?",
        "quote": "Uthumela {send_amount}. Ikupheula ngu-{fee}, ngakho {total} kuyophuma ekhwalini lakho. U-{recipient} uyakuthola {receive_amount} ngezinga {rate}. Uyathumela?",
        "quote_words": "Uthumela {send_amount}. Ikupheula ngu-{fee}, ngakho {total} kuyophuma ehafini yakho. U-{recipient} uyakuthola {receive_amount}.",
        "sent": "Kenziwe. I-{amount} isiphakele ku-{recipient}. Isithenzo sakho ngu-{reference}. Ungakubheka nanini.",
        "scheduled": "Kulungiselwe. Ngizothumela i-{amount} ku-{recipient} ngo-{when}. Isithenzo ngu-{reference}.",
        "cancelled": "Ngikhansele ukhokhelo olulodwa.",
        "status": "Isicelo {reference} siku-{status}. {detail}",
        "status_unknown": "Angitholakalanga isicelo esinombolo {reference}. Sicela uhlole inombolo, noma ungangitshela ukubonisa zakho zakuthuthwa.",
        "history": "Nangu zakho zakuthuthwa: {items}",
        "history_empty": "Awukho nakuphi okuthuthwa okukhona.",
        "rate": "I-{send_currency} ingu-{rate} {receive_currency} namuhla. Leli gingo lingashintsha, ngakho uyakuqinisekisa uma uthumela.",
        "calculated": "Lokhu {amount}, ikupheula ngu-{fee} futhi u-{recipient} uzothola {receive_amount}.",
        "balance": "Una {balance} otholakalayo.",
        "confirm_prompt": "Sicela uqinisekise ukuqhubeka.",
        "confirm_cancel": "Ngikhansele ukhokhelo oluphindaphindayo lwe-{amount} ku-{recipient}?",
        "declined": "Akukho nkinga, ngikhansele lokho.",
        "too_low": "Okuncane okungithumela wona ngu-{minimum}.",
        "too_high": "Okukhulu okungithumela ngokuphathelene ngu-{maximum}.",
        "insufficient_funds": "Una {balance} otholakalayo, futhi akwanele ukulokhu.",
        "backend_down": "Angikwazi ukufinyelela kuMukuru manje. Uzame futhi emva kwesikhashana, futhi akukho okuthuthwa.",
        "expired": "Isiqinisekiso sakho siphelile. Masiqale futhi.",
        "not_enabled": "Ayikho into engingenziwa ngalokho okuManje.",
        "recipient_list": "Ungathumela komani? Ungasho igama, noma unganginika inombolo yocingo.",
        "transaction_item": "{reference}, {amount} ku-{recipient}, {status}",
        "listening": "Ngiyakuzwa.",
        "speaking_error": "Angikwazanga ukukufunda, kodwa ubhalwe lapha.",
        "heard": "Uthe: {text}",
    },
    Language.ST: {
        "greeting": "Lumela. Nka thusa o thusa mme, ho sekema kopo, kapa ho fa seholo sa ho fokolwa. O rata ho etsa jang?",
        "help": "Nka thusa o thusa mme, ho sekema kopo, ho fana seholo, ho bala tjhelete, ho hlama memeo e isanang, kapa ho bona nalale ya hao.",
        "unknown": "Ha ke ka utloisise hantle. O ka kopa thuso o thusa mme, ho sekema kopo, kapa ho fana seholo.",
        "ask_amount": "O ka thusa bokeng?",
        "ask_recipient": "O ka thusa mang?",
        "ask_country": "Chelete e kapa ho?",
        "ask_when": "Nka etsa neng?",
        "ask_reference": "Kopo e o ka bang ho e sekema? O ka fa number ya eona.",
        "unclear_intent": "Ke ka batla hae na le pheha. Na ke thusa mme, sekema kopo, kapa hlama memeo?",
        "quote": "O romela {send_amount}. Tjhelete ya boholo ke {fee}, kahoo {total} ho tsoha mo hodimeng hao. {recipient} o tla fumana {receive_amount} ka sekelo sa {rate}. U romela?",
        "quote_words": "O romela {send_amount}. Tjhelete ya boholo ke {fee}, kahoo {total} ho tsoha mo hodimeng hao. {recipient} o tla fumana {receive_amount}.",
        "sent": "Ho bile. I-{amount} e ya ha {recipient}. Referense ya hao ke {reference}. O ka e sekema neng le neng.",
        "scheduled": "Ho hlama. Ke tla romela i-{amount} ho {recipient} ka {when}. Referense ke {reference}.",
        "cancelled": "Ke kansela memo e hlamilweng.",
        "status": "Kopo {reference} e {status}. {detail}",
        "status_unknown": "Ha ke a bona kopo e referense ya {reference}. Hlola number, kapa ka kope ke bontse zakuthuthwa tsa hao.",
        "history": "Zakuthuthwa tsa hao: {items}",
        "history_empty": "O ha ho na letho le o le romileng.",
        "rate": "I-{send_currency} ke {rate} {receive_currency} kajeno. Sekelo se ka fetoha, kahoo o tla tiiswa ha u roma.",
        "calculated": "Bakeng sa {amount}, boholo ke {fee} mme {recipient} o tla fumana {receive_amount}.",
        "balance": "O na le {balance} e o ka sebetsang.",
        "confirm_prompt": "Ka kopo tiisa.",
        "confirm_cancel": "Ke kansela memo e hlamilweng ya {amount} ho {recipient}?",
        "declined": "Ha ho letho, ke kansela.",
        "too_low": "Boholo bo o ka thusang bo bonyana ke {minimum}.",
        "too_high": "Boholo bo o ka thusang kaofelo ke {maximum}.",
        "insufficient_funds": "O na le {balance} e sebetsang, mme ha ho lekana.",
        "backend_down": "Ha ke kgone ho fihla ko Mukuro hona joale. Kapa lebitsa, mme ha ho letho le o romileng.",
        "expired": "Tingano ya hao e fetile. A re qale.",
        "not_enabled": "Ha ho letho ntle le ntle le ka etsoang hona joale.",
        "recipient_list": "O ka thusa mang? O ka bitsa lebitsa, kapa o ka fa nomoro ya telefono.",
        "transaction_item": "{reference}, {amount} ho {recipient}, {status}",
        "listening": "Ke dutse.",
        "speaking_error": "Ha ke a kgone ho bala, empa bo kwa ntlha.",
        "heard": "O ile wa re: {text}",
    },
}


def render(key: str, language: Language | str, /, **values: object) -> str:
    """Look up a template and fill it in.

    Raises ``KeyError`` for an unknown key or language rather than returning a
    half-built string: a reply the user sees half-written is worse than an
    error in a log.
    """

    from ai.languages import coerce_language

    resolved = coerce_language(language)
    if resolved is None:
        raise KeyError(f"unsupported language: {language!r}")

    table = TEMPLATES[resolved]
    if key not in table:
        raise KeyError(f"{resolved.value} has no template {key!r}")
    return table[key].format(**values)


def available_keys() -> frozenset[str]:
    """Every template key, in any language."""

    keys: set[str] = set()
    for table in TEMPLATES.values():
        keys.update(table)
    return frozenset(keys)


def money(value: Decimal, currency: str = "ZAR") -> str:
    """Format an amount for display, without a trailing ".00"."""

    quantized = value.quantize(Decimal("0.01"))
    text = f"{quantized:,.2f}"
    whole, _, fraction = text.partition(".")
    trimmed = whole if fraction == "00" else text
    return f"{currency} {trimmed}"


__all__ = ["TEMPLATES", "available_keys", "money", "render"]