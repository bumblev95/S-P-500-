"""Conservative, offline event matching for the five homepage news cards.

Only explicit source-title subject/action/target statements are paraphrased.
Unknown constructions stay separate; Korean wording and topic labels alone
never establish identity. Related coverage is retained rather than synthesized.
"""
from datetime import datetime, timezone
from decimal import Decimal
import re
import unicodedata

VERSION = 'source-event-v1'
MAX_FIRST_GAP = 18 * 3600
MAX_UPDATE_GAP = 24 * 3600

ALIASES = (
    (r'\bu\.?s\.?\b|\busa\b|\bamerican\b', 'united states'),
    (r'\bfederal reserve\b', 'fed'),
    (r'\bbank of canada\b', 'boc'), (r'\bbank of england\b', 'boe'),
    (r'\bbank of japan\b', 'boj'), (r'\beuropean central bank\b', 'ecb'),
    (r'\brussian\b', 'russia'), (r'\biranian\b', 'iran'),
    (r'\bchinese\b', 'china'), (r'\beuropean union\b', 'eu'),
    (r'\bzelenskyy\b', 'zelensky'),
)
UNCERTAIN = re.compile(r'\b(could|might|may|would|will|plans?|considers?|expects?|expected|proposes?|denies?|not|never|no longer)\b', re.I)
POLICY = re.compile(r'^(?P<subject>.+?)\s+(?P<action>waives?|waived|lifts?|lifted|suspends?|suspended|imposes?|imposed|extends?|extended|raises?|raised|hikes?|hiked|cuts?|cut|reduces?|reduced|lowers?|lowered|holds?|held)\s+(?P<target>.+)$', re.I)
CORPORATE = re.compile(r'^(?P<subject>.+?)\s+(?P<action>acquires?|acquired|buys?|bought|reports?|reported|posts?|posted)\s+(?P<target>.+)$', re.I)
ACTIONS = {
    **dict.fromkeys(('waive', 'waives', 'waived'), 'waive'),
    **dict.fromkeys(('lift', 'lifts', 'lifted'), 'lift'),
    **dict.fromkeys(('suspend', 'suspends', 'suspended'), 'suspend'),
    **dict.fromkeys(('impose', 'imposes', 'imposed'), 'impose'),
    **dict.fromkeys(('extend', 'extends', 'extended'), 'extend'),
    **dict.fromkeys(('raise', 'raises', 'raised', 'hike', 'hikes', 'hiked'), 'raise'),
    **dict.fromkeys(('cut', 'cuts', 'reduce', 'reduces', 'reduced', 'lower', 'lowers', 'lowered'), 'cut'),
    **dict.fromkeys(('hold', 'holds', 'held'), 'hold'),
    **dict.fromkeys(('acquire', 'acquires', 'acquired', 'buy', 'buys', 'bought'), 'acquire'),
    **dict.fromkeys(('report', 'reports', 'reported', 'post', 'posts', 'posted'), 'report'),
}
# A title with another policy decision or a market reaction can carry a
# distinct material update. Do not reduce it to its first clause.
SECOND_EVENT = re.compile(r'\b(?:waives?|lifts?|suspends?|imposes?|extends?|cuts?|raises?|hikes?|acquires?|buys?)\b|\b(?:stocks?|shares?|prices?|yields?)\s+(?:rise\w*|fall\w*|drop\w*|jump\w*|surge\w*|slid\w*|plunge\w*)\b', re.I)
MARKET_FACTS = re.compile(r'\b(?:sanctions?|restrictions?|tariffs?|trade|exports?|imports?|banks?|interest rates?|policy rates?|earnings?|revenue|profit|stocks?|shares?|bonds?|yields?|oil|energy|inflation|GDP|jobs|merger|acquisition)\b', re.I)
DIRECT_ACTION = re.compile(r'\b(?:waiv\w*|lift\w*|suspend\w*|impos\w*|extend\w*|temporarily ends?|cut\w*|rais\w*|hik\w*|hold\w*|acquir\w*|bought|report\w*|post\w*)\b', re.I)
GENERIC_SUBJECT = re.compile(r'\b(?:investors?|markets?|stocks?|shares?|officials?|leaders?|companies|analysts?|traders?|president|government|bank|it|they|he|she|we|you)\b')


def normalized(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold()
    for pattern, replacement in ALIASES:
        text = re.sub(pattern, replacement, text)
    text = text.replace('$', ' usd ').replace('€', ' eur ').replace('£', ' gbp ')
    return ' '.join(re.findall(r'\d+(?:\.\d+)?%?|[a-z]+', text))


def subject_name(text):
    text = normalized(text)
    text = re.sub(r'^(?:the )?(?:(?:united states )?president )?(?:donald )?(?=trump\b)', '', text)
    text = re.sub(r'^the ', '', text)
    if (not text or len(text.split()) > 5 or GENERIC_SUBJECT.search(text)
            or UNCERTAIN.search(text) or re.search(r'\b(?:and|as|after|on|to|says?)\b', text)):
        return None
    return text


def signature(article):
    """Identify a bounded headline construction, never a background excerpt.

    Scope, numbers, dates, reporting periods and named targets remain in the
    target. Waiver/lifting/suspension and announcement/completion are distinct.
    """
    title = article.get('title', '')
    if not isinstance(title, str) or '?' in title:
        return None
    parts = re.split(r',\s+|;\s+|\s+(?:as|amid|after|while|but|because)\s+', title, maxsplit=1, flags=re.I)
    lead = parts[0]
    if UNCERTAIN.search(lead) or len(parts) > 1 and SECOND_EVENT.search(parts[1]):
        return None
    match = POLICY.fullmatch(lead) or CORPORATE.fullmatch(lead)
    if not match:
        return None
    subject = subject_name(match['subject'])
    if not subject:
        return None
    target = normalized(match['target'])
    action = ACTIONS[match['action'].casefold()]
    if re.search(r'\bsanctions?\b', target):
        kind = 'sanctions'
        if action not in {'waive', 'lift', 'suspend', 'impose', 'extend'}:
            return None
        # These editorial modifiers do not identify a different measure.
        # Preserve all/some, sector names, exemptions, law names and numbers.
        target = re.sub(r'\b(?:broad|new|several|economic|sanctions?|on|against|the)\b', ' ', target)
    elif re.search(r'\btariffs?\b', target):
        kind = 'tariffs'
        if action not in {'waive', 'lift', 'suspend', 'impose', 'extend', 'raise', 'cut'}:
            return None
        target = re.sub(r'\b(?:new|tariffs?|on|against|the)\b', ' ', target)
    elif re.match(r'(?:the )?(?:interest |policy )?rates?\b', target):
        kind = 'rates'
        if action not in {'raise', 'cut', 'hold'}:
            return None
        target = re.sub(r'^(?:the )?(?:interest |policy )?rates?\b', 'rates', target)
    elif action == 'acquire':
        kind = 'acquisition'
    elif action == 'report' and re.search(r'\b(?:earnings|results|profit|revenue)\b', target):
        kind = 'results'
    else:
        return None
    target = ' '.join(target.split())
    if not target or kind in {'sanctions', 'tariffs'} and target == subject:
        return None
    return kind, subject, action, target


def clock(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def close_in_time(left, right):
    first = [clock(a.get('firstPublishedAt') or a.get('publishedAt')) for a in (left, right)]
    updated = [clock(a.get('publishedAt')) for a in (left, right)]
    return (all(first + updated) and all(f <= u for f, u in zip(first, updated))
            and abs((first[0] - first[1]).total_seconds()) <= MAX_FIRST_GAP
            and abs((updated[0] - updated[1]).total_seconds()) <= MAX_UPDATE_GAP)


def same_event(left, right):
    if left.get('category') != right.get('category') or not close_in_time(left, right):
        return False
    a, b = signature(left), signature(right)
    if a and b:
        if a != b:
            return False
        # Conflicting explicit amounts/durations in direct economic source
        # leads are not silently reconciled. Missing details remain inspectable
        # related coverage; different known values require separate cards.
        details = []
        for article in (left, right):
            excerpt = article.get('sourceExcerpt', '')
            values = {}
            if MARKET_FACTS.search(excerpt) and DIRECT_ACTION.search(excerpt):
                for number, unit in re.findall(r'\b(\d+(?:\.\d+)?)\s*(basis points?|percentage points?|percent|%|days?|months?|years?|billion|trillion)(?!\w)', excerpt, re.I):
                    unit = unit.casefold().rstrip('s')
                    value = Decimal(number)
                    if unit in {'basis point', 'percentage point'}:
                        value *= 100 if unit == 'percentage point' else 1
                        unit = 'basis point'
                    elif unit in {'percent', '%'}:
                        unit = 'percent'
                    values.setdefault(unit, set()).add(value)
            details.append(values)
        return all(details[0][unit] == details[1][unit] for unit in details[0].keys() & details[1].keys())
    # Exact syndication is safe only with a substantive identical source lead.
    # A recurring generic title or a shared Korean translation is insufficient.
    title = normalized(left.get('title'))
    excerpt = normalized(left.get('sourceExcerpt'))
    return (len(title.split()) >= 6 and len(excerpt.split()) >= 8
            and title == normalized(right.get('title'))
            and excerpt == normalized(right.get('sourceExcerpt')))


def representative_score(article):
    """Favor explicit economic evidence and a substantive, source-bound lead.

    No publisher preference or cross-source rewriting. Source freshness and
    translation completeness break content ties, followed by time and URL.
    """
    title = article.get('title', '')
    excerpt = article.get('sourceExcerpt', '')
    facts = {m[0].casefold() for m in MARKET_FACTS.finditer(title + '\n' + excerpt)}
    direct = bool(MARKET_FACTS.search(excerpt) and DIRECT_ACTION.search(excerpt))
    substantive = normalized(excerpt) != normalized(title) and len(excerpt.split()) >= 8
    return (int(direct), len(facts), int(substantive),
            min(len(excerpt.split()), 60), article.get('translationStatus') == 'ready',
            not article.get('fromCache', False),
            clock(article.get('publishedAt')) or datetime.min.replace(tzinfo=timezone.utc), article.get('url', ''))


def public_article(article):
    return {k: v for k, v in article.items() if not k.startswith('_') and k not in {'sourceExcerpt', 'relatedCoverage'}}


def group_coverage(articles, usable, limit=5):
    """Group before limiting, with complete-link matching to prevent chains.

    Keep every source in the collector cache. Non-displayable translations can
    supply related source evidence but can never displace a displayable card.
    """
    groups = []
    ordered = sorted(articles, key=lambda a: (clock(a.get('publishedAt')) or datetime.min.replace(tzinfo=timezone.utc), a.get('url', '')), reverse=True)
    for article in ordered:
        group = next((g for g in groups if all(same_event(article, other) for other in g)), None)
        if group is None:
            groups.append([article])
        else:
            group.append(article)
    cards = []
    for group in groups:
        candidates = [a for a in group if usable(a)]
        if not candidates:
            continue
        representative = max(candidates, key=representative_score)
        card = public_article(representative)
        related = []
        seen = {representative.get('url')}
        for other in group:
            if other.get('url') in seen:
                continue
            seen.add(other.get('url'))
            record = public_article(other)
            # Preserve exact leads and hashes for inspecting additional facts;
            # do not merge translations, write a combined summary or infer facts.
            if other.get('sourceExcerpt'):
                record['sourceExcerpt'] = other['sourceExcerpt']
            record['additionalContext'] = (normalized(other.get('sourceExcerpt'))
                                           != normalized(representative.get('sourceExcerpt')))
            if not usable(other):
                for field in ('headlineKo', 'summaryKo'):
                    record.pop(field, None)
                record['translationStatus'] = 'unavailable'
            related.append(record)
        if related:
            card['relatedCoverage'] = related
        cards.append(card)
    # Use the representative's actual publication time, not a fresher sibling's
    # timestamp. Importance remains a tie-breaker, never a pin.
    return sorted(cards, key=lambda a: (clock(a.get('publishedAt')) or datetime.min.replace(tzinfo=timezone.utc),
                                       a.get('importance') == 'important', a.get('url', '')), reverse=True)[:limit]
