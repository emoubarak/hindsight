"""Shared by the hooks and the miner: spot corrections and recall requests, redact secrets.

Pattern lists are per language. English is on by default; set HINDSIGHT_LANGS=en,fr to add French.
A false positive costs one log line, a miss loses a lesson, so the correction detector leans inclusive
but keeps plain requests ("can you do X?") out unless they come with another marker.
"""
import os
import re

CORRECTION = {
    "en": {
        "strong": [
            r"\bI (?:already |just )?(?:told|asked|said) (?:you|to)\b", r"\bas I (?:said|told you|mentioned)\b",
            r"\bI (?:said|asked for)\b.{0,40}\bnot\b", r"\bnot what I (?:asked|wanted|meant|said)\b",
            r"\bI didn'?t (?:ask|say|want)\b", r"\bwe (?:already )?(?:discussed|agreed|decided)\b",
            r"\bthat'?s (?:not|wrong|incorrect|not right)\b", r"\bthat'?s not how\b", r"\bnot like that\b",
            r"\bwhy did you\b", r"\byou (?:forgot|missed|ignored|didn'?t|never)\b",
            r"\bstop (?:doing|adding|using|making|being|writing)\b", r"\bplease (?:stop|don'?t)\b",
            r"\bnever (?:do|use|add|change|touch|write)\b", r"\bstill (?:not|doesn'?t|isn'?t|wrong|broken)\b",
            r"\b(?:second|third|fourth|fifth|\d+(?:st|nd|rd|th)) time\b", r"\bundo that\b|\brevert (?:that|this)\b",
            r"\bmade (?:that|this|it) up\b|\byou'?re (?:making|inventing)\b|\bhallucinat",
        ],
        "weak": [
            r"^(?:no|nope|wrong)\b", r"\bwrong\b", r"\bnot working\b|\bdoesn'?t work\b|\bbroken\b",
            r"\btoo (?:long|verbose|complex|complicated|much|big|small|noisy)\b", r"\bsimpler\b|\bshorter\b",
            r"\bare you sure\b", r"\bmissing\b", r"\bpointless\b|\bnot useful\b",
        ],
    },
    "fr": {
        "strong": [
            r"\bj(?:e )?t'?(?:ai|é) (?:dit|dis|demand[ée])", r"\bj'?(?:ai|é) (?:dit|dis|demand[ée])\b",
            r"\bon avait dit\b", r"\bcomme (?:je|j)(?:e)? ?(?:t'?ai|l'?ai) dit", r"\b(?:toujours|tjr?s?) pas\b",
            r"\bencore (?:une fois|pas|trop)\b", r"\b(?:\d+|deuxi[eè]me|troisi[eè]me)e? fois\b",
            r"\bc'?(?:est)? ?pas (?:[çc]a|bon|ce que)\b", r"\bc'est faux\b", r"\bn'importe quoi\b",
            r"\btu (?:m'as )?menti\b|\btu inventes?\b", r"\bt'as rien compris\b|\bta pas compris\b",
            r"\b(?:pourquoi|pk|pq) (?:tu|t'as|ta)\b", r"\bt'?(?:as|a) (?:pas|oubli[ée])\b",
            r"\barr[eê]te (?:de|d'|avec)\b", r"\bj'?(?:ai|é) pas demand[ée]\b", r"\bfais gaffe\b",
        ],
        "weak": [
            r"^(?:non|nan)\b", r"\bfaux\b", r"\btrop (?:long|charg[ée]|compliqu[ée]|gros|petit)\b",
            r"\bplus (?:simple|court)\b", r"\bne (?:marche|fonctionne) pas\b", r"\bt'es s[uû]r\b",
        ],
    },
}

RECALL = {
    "en": [
        r"do you remember", r"remember (?:when|what|that)", r"\bI (?:told|gave|sent|showed) you\b",
        r"\bwhere (?:were we|did we leave)\b", r"\bwe (?:left off|were working on)\b",
        r"\blike (?:last time|the other day|before)\b", r"\bin (?:the|that) (?:other|previous|last) (?:session|chat|conversation)\b",
        r"\bwe (?:already )?(?:did|decided|discussed|set up|fixed|talked about)\b",
        r"\bwhat did we (?:do|decide|say|use)\b", r"\bfind (?:the|that) (?:session|conversation|chat)\b",
    ],
    "fr": [
        r"tu te souviens", r"souviens[- ]toi", r"rappelle[- ]toi", r"on en (?:était|etait) o[uù]",
        r"comme (?:la dernière fois|l'autre fois)", r"l'autre (?:session|conv)", r"on avait (?:dit|fait|vu|décidé)",
        r"je t'?(?:ai|avais) (?:donn|envoy|mis|dit)",
    ],
}

NOISE = ("<task-notification", "<system-reminder", "<local-command", "<command-name>/clear")


def langs():
    return [l.strip() for l in os.environ.get("HINDSIGHT_LANGS", "en").split(",") if l.strip() in CORRECTION]


def _compiled(table, key=None):
    out = []
    for l in langs():
        pats = table[l] if key is None else table[l][key]
        out += [re.compile(p, re.I) for p in pats]
    return out


def score(text):
    """2 per strong marker, 1 per weak one; >= 2 is treated as a correction."""
    if not text or text.lstrip().startswith(NOISE):
        return 0, []
    head = text[:1500]
    strong = [m.group(0) for r in _compiled(CORRECTION, "strong") if (m := r.search(head))]
    weak = [m.group(0) for r in _compiled(CORRECTION, "weak") if (m := r.search(head))]
    return 2 * len(strong) + len(weak), strong + weak


def is_recall(text):
    head = (text or "")[:2000]
    return any(r.search(head) for r in _compiled(RECALL))


_KEYWORDS = r"(?:password|passwd|pwd|passphrase|mdp|mot de passe)"
_LONG = r"(?:password|passwd|passphrase|secret|token|api_?key|apikey|access_?key|private_?key)"
_NAMES = r"(?:" + _LONG + r"|(?<![A-Za-z])(?:pass|pwd|pw|auth)(?![A-Za-z]))"   # inside an identifier: PGPASSWORD, DB_PASS, accessToken
_SECRETS = [
    # quoted values first, masked whole: PASSWORD="a b c"
    (re.compile(r"(?i)\b([\w.-]*" + _NAMES + r"[\w.-]*\s*[=:]\s*)(\"[^\"]*\"|'[^']*')"), r"\1[secret]"),
    # "password is X", "password for the db is X", "mdp sudo c'est X", "wifi password: X"
    (re.compile(r"(?i)\b(" + _KEYWORDS + r")((?:\s+[\w.-]{1,14}){0,3}?\s*(?:is|=|:|c'est|c est|est)\s*)([^\s,;]{4,})"), r"\1\2[secret]"),
    (re.compile(r"(?i)\b(\w+\s+" + _KEYWORDS + r")(\s*(?:is|=|:|c'est|c est|est)\s*)([^\s,;]{4,})"), r"\1\2[secret]"),
    (re.compile(r"(?i)\b(" + _KEYWORDS + r"(?:\s+[\w.-]{1,14})?\s+)(?=[^\s,;]*\d)(?=[^\s,;]*[A-Za-z])([^\s,;]{6,})"), r"\1[secret]"),
    # ENV_STYLE=value and key=value where the name carries a secret word (DB_PASSWORD=..., GITHUB_TOKEN=...)
    (re.compile(r"(?i)\b([\w.-]*" + _NAMES + r"[\w.-]*\s*[=:]\s*)(?![\"'\[{])[^\s,;]{4,}"), r"\1[secret]"),
    # JSON: "api_key": "...", "password": "..."
    (re.compile(r"(?i)([\"'][\w-]*" + _NAMES + r"[\w-]*[\"']\s*:\s*[\"'])[^\"']{3,}([\"'])"), r"\1[secret]\2"),
    (re.compile(r"(?i)(--(?:password|passwd|token|secret|api-key|apikey|auth-token|access-token)(?:=|\s+))[^\s-][^\s]{3,}"), r"\1[secret]"),
    (re.compile(r"\b(mysql(?:dump|admin)?\b[^\n|;]*?\s-p)([^\s]{4,})"), r"\1[secret]"),
    (re.compile(r"(?i)\b(aws[\w ]{0,25}?)\b([A-Za-z0-9/+=]{40})\b"), r"\1[secret]"),
    (re.compile(r"(?i)\b(passcode|pin code|otp|one-time code|code de v[ée]rification)(\s*(?:is|:|=|est)?\s*)(\d{4,8})\b"), r"\1\2[secret]"),
    (re.compile(r"(?i)\b(api[ _-]?key|secret|token|client_secret)(\s*(?:is|=|:)\s*)([^\s,;\[]{8,})"), r"\1\2[secret]"),
    (re.compile(r"(://[^/\s:@]*:)[^/\s@]+(@)"), r"\1[secret]\2"),                      # postgres://user:pass@host, redis://:pw@host
    (re.compile(r"(?i)\b(sshpass\s+-p\s*|curl\s+(?:-u|--user)\s+[^\s:]*:)([^\s]{4,})"), r"\1[secret]"),
    (re.compile(r"(?i)\b(echo\s+)(\S{4,})(\s*\|\s*sudo\s+-S)"), r"\1[secret]\3"),
    (re.compile(r"(?i)\b(authorization:\s*(?:basic|token)\s+)\S{8,}"), r"\1[secret]"),
    (re.compile(r"https://(?:hooks\.slack\.com/services|discord(?:app)?\.com/api/webhooks)/\S+"), "[secret webhook]"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[secret]"),
    (re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}"), "[secret]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), "[secret]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[secret]"),
    # well-known vendor token shapes
    (re.compile(r"\b(?:GOCSPX-[\w-]{20,}|ya29\.[\w-]{20,}|re_[A-Za-z0-9_]{20,}|SG\.[\w-]{16,}\.[\w-]{16,}|"
                r"glpat-[\w-]{16,}|npm_[A-Za-z0-9]{30,}|hf_[A-Za-z0-9]{30,}|dop_v1_[a-f0-9]{30,}|"
                r"(?:sk|pk|rk)_(?:live|test)_\w{10,}|xapp-[\w-]{20,}|shpat_[a-f0-9]{30,}|"
                r"\d{8,10}:[A-Za-z0-9_-]{34,})"), "[secret]"),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|AKIA[0-9A-Z]{16}|xox[abp]-[\w-]{10,})"), "[secret]"),
    (re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}"), "[secret]"),
    # a key cut off by truncation still has no END line: take everything to the end of the text
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"), "[private key]"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "[secret?]"),
    (re.compile(r"(?<![/\w.-])[A-Za-z0-9_\-]{40,}(?![/\w.-])"), "[secret?]"),
]


def redact(text):
    """What gets archived must not keep the passwords and tokens pasted in chat. Always redact BEFORE truncating:
    a cut-off key or token would otherwise slip past the patterns."""
    for rx, sub in _SECRETS:
        text = rx.sub(sub, text)
    return text
