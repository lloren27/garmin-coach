"""Conservative allow-list of explicit requests; contextual fatigue is not consent."""
import re
import unicodedata


def requests_plan_change(text: str) -> bool:
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.lower())
                   if not unicodedata.combining(c)).strip()
    if any(c in text for c in ('"', "'", '«', '»', '“', '”', '`')):
        return False
    if re.match(r'^no\s*[,;.!?]', text):
        return False
    if re.search(r'\b(?:si|quizas|quiza|explica|explicar|significa|significado|ejemplo|dice|dijo)\b',
                 re.sub(r'^si\s*[,!.]\s*', '', text)):
        return False
    action = r'(?:ajust\w*|reorganiz\w*|cambi\w*|modific\w*|reprogram\w*)'
    if re.search(r'\b(?:no|nunca|jamas|sin)\b[^,;.?!]*\b' + action, text):
        return False
    if re.search(r'\b' + action + r'[^,;.?!]*\bno\s*[.!?]*$', text):
        return False
    if re.match(r'^/ajustar(?:@\w+)?(?:\s|$)', text):
        return True
    imperative = r'(?:ajusta(?:me|lo)?|reorganiza(?:me|lo)?|cambia(?:me|lo)?|modifica(?:me|lo)?|reprograma(?:me|lo)?)'
    request = r'(?:me\s+(?:ajustas|reorganizas|cambias|modificas|reprogramas)|(?:puedes|podrias)\s+(?:ajustar|reorganizar|cambiar|modificar|reprogramar)(?:me|lo)?)'
    return bool(re.search(r'(?:^|[,;.!?¿]\s*)(?:por favor\s*,?\s*)?(?:' + imperative + '|' + request + r')\b', text))
