"""Stable coordination identities. These never alter material calculations."""
import hashlib
import json
from decimal import Decimal
from datetime import datetime
from urllib.parse import urlencode
import pytz


def decision_context(value, option, arrival, zone, language, order_id, line_id):
    """Describe the validated candidate, never client-supplied prose or links."""
    lang = (language or 'en').split('_')[0]
    labels = {
        'zh': ('保持现有分配', '调 {quantity} {unit} 给 {order}', '调整 {count} 张制造单的材料分配', '假设到货', '方案', '物料', '返回情景与核实进度'),
        'en': ('Keep the current allocation', 'Move {quantity} {unit} to {order}', 'Reallocate material across {count} manufacturing orders', 'Scenario arrival', 'Option', 'Material', 'Return to this scenario and review progress'),
        'fr': ('Conserver l’affectation actuelle', 'Transférer {quantity} {unit} à {order}', 'Réaffecter la matière de {count} ordres', 'Arrivée du scénario', 'Option', 'Matière', 'Revenir au scénario et au suivi'),
    }.get(lang)
    if labels is None:
        return decision_context(value, option, arrival, zone, 'en', order_id, line_id)
    report = value['report']
    rows = {row['ref']: row for row in report['rows']}
    moves = option['comparison']['plan']['transfers']
    if not moves:
        title = labels[0]
    elif len(moves) == 1:
        move = moves[0]
        title = labels[1].format(quantity=format(Decimal(str(move['quantity'])).normalize(), 'f'),
                                unit=report['unit'], order=rows[move['receiver_ref']]['mo'])
    else:
        affected = {m[k] for m in moves for k in ('receiver_ref', 'donor_ref') if m.get(k) in rows}
        title = labels[2].format(count=len(affected))
    moment = datetime.fromisoformat(arrival)
    if moment.tzinfo is None:
        raise ValueError('Timezone-aware scenario required')
    stamp = moment.astimezone(pytz.timezone(zone)).strftime('%Y-%m-%d %H:%M') + ' (' + zone + ')'
    url = '/odoo/action-material_delay_impact?' + urlencode({
        'active_id': order_id, 'mdic_line': line_id, 'mdic_arrival': arrival, 'mdic_tz': zone})
    return {'title': title, 'arrival_label': labels[3], 'stamp': stamp,
            'lines': [labels[4] + ': ' + title, labels[3] + ': ' + stamp,
                      labels[5] + ': ' + report['product']], 'url': url, 'link_label': labels[6]}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def option_key(option):
    moves = [[m.get(k) for k in ('source_ref', 'donor_ref', 'receiver_ref')] +
             [str(Decimal(str(m['quantity'])).normalize())]
             for m in option['comparison']['plan']['transfers']]
    return digest(sorted(moves, key=str))


def targets(option):
    result = []
    support = option.get('decision_support') or {}
    for category in ('actions', 'conditions'):
        for item in support.get(category, []):
            kind = item['kind']
            if kind == 'gap_target':
                continue
            role = ('warehouse' if kind == 'coordinate_transfer' else 'purchasing') if category == 'actions' else (
                'warehouse' if kind == 'release_reservation' else
                'plannerRole' if kind in ('accept_harm', 'priority_conflict') else 'production')
            key = digest([category, role, [item.get(k) for k in ('kind', 'ref', 'source_ref', 'donor_ref')]])
            result.append({'key': key, 'role': role, 'actions': [item] if category == 'actions' else [],
                           'conditions': [item] if category == 'conditions' else []})
    return result
