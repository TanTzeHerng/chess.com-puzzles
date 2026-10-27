"""Rating graph samples are scored puzzle events, never timer ticks."""
import math

def scored_history(previous, recent, bins, current_rating, initial=2500, rd=350):
    events = {int(e['id']): e for e in previous.get('rating_events', [])}
    for result in recent:
        status = result.get('status')
        if status not in ('solved', 'missed'):
            continue
        score = 1 if status == 'solved' else 0
        if result.get('score') != score:
            continue
        events[int(result['id'])] = {
            'id': int(result['id']), 'rating': int(result['rating']),
            'score': score, 'utc': result['finished_at'],
        }
    ordered = sorted(events.values(), key=lambda e: (e['utc'], e['id']))
    total = sum(sum(pair) for pair in bins.values())
    observed = {}
    for event in ordered:
        pair = observed.setdefault(str(event['rating']), [0, 0])
        pair[0 if event['score'] else 1] += 1
    complete = observed == {str(k): list(v) for k, v in bins.items() if sum(v)}
    if complete:
        points = []
        q = math.log(10) / 400
        information = surprise = 0.0
        for attempt, event in enumerate(ordered, 1):
            expected = 1 / (1 + 10 ** ((event['rating'] - initial) / 400))
            information += q * q * expected * (1 - expected)
            surprise += event['score'] - expected
            rating = initial + q * surprise / (1 / (rd * rd) + information)
            points.append({'puzzle_id': event['id'], 'attempt': attempt,
                           'utc': event['utc'], 'rating': rating})
        return points, ordered, 0
    # If a long outage hid old events, keep real samples and mark the gap.
    # Do not invent intermediate ratings from aggregate win/loss counts.
    points = [p for p in previous.get('trend', [])
              if 'puzzle_id' in p and 0 < p.get('attempt', 0) <= total]
    compatible = all(v[i] <= bins.get(k, [0, 0])[i]
                     for k, v in observed.items() for i in (0, 1))
    if compatible and ordered and total > max((p['attempt'] for p in points), default=0):
        event = ordered[-1]
        if not any(p['puzzle_id'] == event['id'] for p in points):
            points.append({'puzzle_id': event['id'], 'attempt': total,
                           'utc': event['utc'], 'rating': current_rating})
    return points, ordered, max(0, total - len(ordered))
