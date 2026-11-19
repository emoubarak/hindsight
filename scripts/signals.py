"""Shared by the hooks and the miner: spot corrections and recall requests, redact secrets.

Pattern lists are per language. English is on by default; set HINDSIGHT_LANGS=en,fr to add French. The English
lists were tuned on public messages people sent to coding agents (GitHub issues of Claude Code, shared sessions): on the
held-out half they catch about half of the corrections and flag about 3 in 100 ordinary messages of a random sample.
Weak markers are deliberately not duplicated across lists: two weak hits make a correction.
A false positive costs one log line, a miss loses a lesson, so the correction detector leans inclusive
but keeps plain requests ("can you do X?") out unless they come with another marker.
"""
import os
import re


def _config_dir():
    """Same rule as paths.CONFIG, repeated here so this file works on its own (it is also embedded elsewhere)."""
    return os.environ.get("HINDSIGHT_CONFIG") or os.path.join(os.path.expanduser("~"), ".config/hindsight")

CORRECTION = {
    "en": {
        "strong": [
            r"\bI (?:already )?(?:told|asked) you\b", r"\b(?:as|like) I (?:said|told you|asked)\b",
            r"\bI (?:said|asked for)\b[^.?!\n]{0,40}\bnot\b", r"\bnot what I (?:asked|wanted|meant|said)\b",
            r"\bI (?:never|didn'?t|did not) (?:ask|say|want)\b", r"\bwhy (?:did|do|would|are|is) you\b",
            r"\byou (?:forgot|missed|ignored|skipped|broke|deleted|overwrote|keep|still)\b",
            r"\byou (?:didn'?t|did not|never|haven'?t|have not)\b",
            r"\b(?:still|again) (?:not|wrong|broken|failing|the same)\b",
            r"\bstill (?:doesn'?t|isn'?t|won'?t|don'?t)\b", r"\b(?:once|yet) again\b",
            r"\bfor the (?:\w+ )?(?:second|third|fourth|fifth|tenth|nth|last) time\b", r"\bhow many times\b",
            r"\b(?:stop|quit) (?:doing|adding|using|asking|making|writing|changing)\b",
            r"\bnever (?:do|use|add|touch|change|create|delete|ask|write|push|commit)\b",
            r"\bthat'?s (?:wrong|incorrect|not (?:right|it|what))\b", r"\byou(?:'re| are) wrong\b",
            r"\b(?:you )?made (?:that|this|it) up\b", r"\bhallucinat\w*",
            r"\bwrong (?:file|place|folder|branch|again)\b", r"\bthat'?s not how\b", r"\bdid I ask\b",
            r"\bwho (?:asked|said)\b",
            r"\bstill (?:see|seeing|shows?|showing|fails?|failing|broken|gets?|getting|got|there|happen\w*|incorrect|appears?|becom\w*|missing|empty|wrong|off|the same|not|no\b|doesn'?t|isn'?t|won'?t|can'?t|creat\w*|play\w*|blink\w*|darker|lighter|visible|a (?:line|bit|lot|problem|bug|moment|gap))",
            r"^\s*(?:again|still)\b",
            r"^\s*no[,.:!]\s(?!(?:go|problem|worries|thanks|need)\b)|^\s*no but\b|^\s*(?:sorry,? )?no[,.!]?\s*$",
            r"\bwhy (?:isn'?t|wasn'?t|didn'?t|doesn'?t|don'?t|won'?t|can'?t|aren'?t|is it still|does it still|do I still)\b",
            r"\bdid you (?:really|even|actually|just|lie)\b",
            r"\bare you (?:kidding|serious|joking|intentionally|even|taking|ignoring|listening)\b",
            r"\bI (?:never|didn'?t|did not) (?:said|told|wrote|asked|approved|agreed)\b",
            r"\bI never (?:said|told|wrote|asked)\b", r"\bwhat I (?:said|asked|told you|wanted)\b",
            r"\byou (?:refused?|lied|lie to|retried|clobbered|reverted|removed|ignore|changed)\b",
            r"\byou(?:'re| are) (?:not|hacking|lying|ignoring|exhausting|running|in the wrong|making (?:it|this|that|things) up)\b",
            r"\b(?:what the f\w*|wtf|fuck you)\b", r"\b(?:stop|quit) (?:\w+ing)\b",
            r"^\s*(?:just )?(?:\w+ )?stop\s*[!.]*\s*$", r"\byou \w+ed\b[^.?!\n]{0,40}\bagain\b",
            r"\bnothing (?:changed|happened|works)\b", r"\bwhat are you doing\b", r"\bover and over\b",
            r"\byou(?:'ve| have)? (?:repeatedly|repeated)\b", r"\bdid you not\b", r"\bwhy do I (?:have|need) to\b",
            r"\b(?:not|un)acceptable\b", r"\bnot (?:quite|exactly) (?:there|right|it|what)\b|\bstill not it\b",
            r"\bwe (?:already )?(?:discussed|agreed|decided)\b",
        ],
        "weak": [
            r"^(?:no|nope|nah|wrong)\b", r"\b(?:simpler|shorter)\b",
            r"(?<!don't )(?<!dont )(?<!not )\bstop\b", r"\bwrong\b", r"\bbroken\b", r"\bdoes(?:n'?t| not) work\b",
            r"\bnot working\b", r"\btoo (?:long|verbose|much|complicated|many|big|small)\b",
            r"\btrop (?:long|charg[ée]|compliqu[ée])\b", r"\bdon'?t\b", r"\binstead\b", r"\bactually\b",
            r"\bre-?read\b", r"\bugly\b", r"\bmissing\b", r"\bundo\b|\brevert\b", r"\bare you sure\b",
            r"\bbug(?:gy)?\b", r"\bhow come\b",
            r"\b(?:does|did)(?:n'?t| not) (?:show|seem|do|get|change|update|appear|load|fix|happen|work)\b",
            r"\bdid not get\b", r"\bagain\b", r"\bnot the \w+|, not (?:the|in|a|an|on|my)\b", r"^\s*not\b",
            r"\bwhy (?:is|does) (?:it|this|that|there)\b", r"\bstep back\b", r"\bno need to\b", r"^\s*wait\b",
            r"\bwhere did you\b", r"\bwhat happened to\b", r"\bit should (?:be|contain|show|have|not)\b",
            r"\byou (?:have|need) to (?:look|read|use|check)\b", r"\b(?:fucking|shit|damn)\b",
            r"\bI asked (?:to|for)\b", r"\byou just\b",
        ],
        # case matters here: capitals are shouting
        "strong_case": [
            r"\b(?:DO NOT|DON'?T|NEVER|STOP)\b",
        ],
        # case matters here: capitals are shouting
        "weak_case": [
            r"\b[A-Z]{2,}(?:\s+[A-Z']{2,}){2,}\b",
        ],
    },
    "fr": {
        "strong": [
            r"\bj(?:e )?t'?(?:ai|é) (?:dit|dis|demand[ée])", r"\bj'?(?:ai|é) (?:dit|dis|demand[ée])\b",
            r"\bon avait dit\b", r"\bcomme (?:je|j)(?:e)? ?(?:t'?ai|l'?ai) dit", r"\b(?:toujours|tjr?s?) pas\b",
            r"\bencore (?:une fois|en |pas|trop|des?)\b", r"\bencore (?:l'|le\b)",
            r"\b(?:\d+|deuxi[eè]me|troisi[eè]me|dixi[eè]me|quinzi[eè]me|[eé]ni[eè]me)e? fois\b",
            r"\bc'?(?:est)? ?pas (?:[çc]a|bon|ce que)\b", r"\bc (?:faux|pas bon|nul)\b", r"\bc'est faux\b",
            r"\bn'importe quoi\b", r"\bslop\b",
            r"\bmensonge\b|\btu (?:m'as )?menti?s?\b|\btu inventes?\b|\binvent[ée] des?\b",
            r"\bj'y comprends? (?:plus )?rien\b|\btu me perds?\b|\bt'as rien compris\b|\bta pas compris\b",
            r"\b(?:pourquoi|pk|pq|pkoi) (?:tu|t'as|ta|t'es)\b", r"\bt'?(?:as|a) (?:pas|oubli[ée]|rien)\b",
            r"\btu as (?:pas|oubli[ée])\b", r"\bt'es pas all[ée]\b", r"\barr[eê]te (?:de|d'|avec|toi)\b",
            r"\bj'?(?:ai|é) pas demand[ée]\b", r"\bj(?:e )?(?:veux|veu) pas\b", r"\bje te l'ai d[ée]j[àa]\b",
            r"\bfait gaffe\b|\bfais gaffe\b", r"\bpas fid[eè]le\b", r"\bencore (?:une fois|pas|trop)\b",
            r"\b(?:\d+|deuxi[eè]me|troisi[eè]me|dixi[eè]me|[eé]ni[eè]me)e? fois\b",
            r"\btu (?:m'as )?menti?s?\b|\btu inventes?\b", r"\bt'as rien compris\b|\btu n'as (?:rien|pas) compris\b",
            r"(?<!pas )\bencore (?:des?|en|du|l[ae'])\b",
            r"\bencore une? (?:souci|soucis|erreur|probl[eè]me|bug|hic)\b", r"\bfai[ts] gaffe\b",
            r"\bmoche\b|\bd[ée]gueu\b", r"\bmensonge\b|\binvent[ée]e?s? des?\b",
            r"\bj'y comprends? (?:plus )?rien\b|\btu me perds?\b", r"\bta pas compris\b|\bt'es pas all[ée]\b",
        ],
        "weak": [
            r"\brelis\b", r"\bfaux\b", r"\bnul(?:le)?\b", r"\btu (?:peux|pourrais) pas\b", r"\btu ne peux pas\b",
            r"\bplus (?:simple|court|subtil)", r"\btrop (?:long|de texte|charg[ée]|compliqu[ée]|gros|petit)\b",
            r"\bmanque\b", r"\bt'es s[uû]r\b", r"\btej\b", r"\bsans int[ée]r[eê]t\b", r"\bon s'en fout\b",
            r"\bc(?:a|ç)a? (?:marche|fonctionne) (?:pas|toujours pas)\b", r"\bne (?:marche|fonctionne) pas\b",
            r"\b(?:marche|fonctionne) pas\b", r"\bj(?:e )?veux pas\b", r"\bcheap\b", r"\bplus subtil\b",
            r"\btrop (?:de texte|gros|petit)\b", r"^(?:non|nan)\b",
            r"\b(?:ne )?(?:marche|fonctionne) (?:pas|plus)\b", r"\b(?:plus simple|plus court)\b",
            r"\bmoche\b",
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
        r"tu te souviens", r"souviens[- ]toi", r"rappelle[- ]toi", r"je t[' ’]?ai (?:donn|envoy|mis|file|pass)",
        r"je t[' ’]?avais", r"j[' ’]?t[' ’]?avais", r"\bt[' ’]?avais (?:donn|envoy|mis|cr|fait|trouv|lanc|dit)",
        r"on en (?:était|etait) o[uù]", r"on (?:s[' ’]?)?(?:était|etait) arr[eê]t", r"on avait (?:dit|fait|vu|parl|décid|mis|lanc|trouv|cr)",
        r"comme (?:la dernière fois|l[' ’]?autre fois)", r"l[' ’]?autre (?:session|conv)", r"(?:dans|de) (?:la|une) (?:session|conv) d[' ’]?avant",
        r"tu avais (?:fait|dit|trouvé)", r"déjà donné", r"retrouve[rs]? (?:la|le|les|ma|mon|mes) (?:session|conv|discussion|mdp|mot de passe)",
    ],
}

NOISE = ("<task-notification", "<system-reminder", "<local-command", "<command-name>/clear", "Caveat:")
# a message that opens with a tag (<pasted_content>, <agent-message>…) is pasted or relayed text, not the user speaking
_TAGGED = re.compile(r"\s*<[a-z][\w-]*[ >]")


def langs():
    return [l.strip() for l in os.environ.get("HINDSIGHT_LANGS", "en").split(",") if l.strip() in CORRECTION]


def _compiled(table, key=None, flags=re.I):
    out = []
    for l in langs():
        pats = table[l] if key is None else table[l].get(key, [])
        out += [re.compile(p, flags) for p in pats]
    return out


_EXTRA = None


def _extra():
    """Your own strong patterns: one regex per line in $HINDSIGHT_CONFIG/patterns.txt (blank lines and # comments
    ignored), and/or HINDSIGHT_EXTRA_PATTERNS (newline-separated). Each counts as a strong marker."""
    global _EXTRA
    if _EXTRA is None:
        _EXTRA, lines = [], os.environ.get("HINDSIGHT_EXTRA_PATTERNS", "").splitlines()
        try:
            lines += open(os.path.join(_config_dir(), "patterns.txt"), encoding="utf-8").read().splitlines()
        except OSError:
            pass
        for p in lines:
            if p.strip() and not p.lstrip().startswith("#"):
                try:
                    _EXTRA.append(re.compile(p.strip(), re.I))
                except re.error:
                    pass
    return _EXTRA


def score(text):
    """2 per strong marker, 1 per weak one; >= 2 is treated as a correction."""
    if not text or text.lstrip().startswith(NOISE) or _TAGGED.match(text):
        return 0, []
    head = text[:1500]
    strong = [m.group(0) for r in _compiled(CORRECTION, "strong") + _compiled(CORRECTION, "strong_case", 0) + _extra()
              if (m := r.search(head))]
    weak = [m.group(0) for r in _compiled(CORRECTION, "weak") + _compiled(CORRECTION, "weak_case", 0)
            if (m := r.search(head))]
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
    # "uuid:hex" keys (e.g. an exchange API key and its secret)
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:[0-9a-f]{16,}\b", re.I), "[secret]"),
    # "clé api c'est X", "token est X", "client_secret = X", "api key: X"
    (re.compile(r"(?i)\b(cl[eé]f?s?(?:\s+(?:api|priv[ée]e?))?|api[ _-]?key|token|secret|client_secret)"
                r"(\s*(?:c'est|c est|c|est|is|:|=)\s*)([^\s,;\[]{8,})"), r"\1\2[secret]"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "[secret?]"),
    (re.compile(r"(?<![/\w.-])[A-Za-z0-9_\-]{40,}(?![/\w.-])"), "[secret?]"),
]


_TOKEN = re.compile(r"[^\s,;'\"`()\[\]<>]{6,}")
_HASHES = None


def _known():
    """SHA-256 of secrets you declared (one hash per line in $HINDSIGHT_CONFIG/secret-hashes, see `mine.py secret`):
    the value itself is never stored, yet every occurrence is erased from what gets archived."""
    global _HASHES
    if _HASHES is None:
        try:
            _HASHES = {l.strip() for l in open(os.path.join(_config_dir(), "secret-hashes")) if l.strip()}
        except OSError:
            _HASHES = set()
    return _HASHES


def redact(text):
    """What gets archived must not keep the passwords and tokens pasted in chat. Always redact BEFORE truncating:
    a cut-off key or token would otherwise slip past the patterns."""
    for rx, sub in _SECRETS:
        text = rx.sub(sub, text)
    if _known():
        import hashlib
        text = _TOKEN.sub(lambda m: "[secret]" if hashlib.sha256(m.group(0).encode()).hexdigest() in _HASHES
                          else m.group(0), text)
    return text
