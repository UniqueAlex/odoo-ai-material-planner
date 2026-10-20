"""Bounded change detection for an already authorized shared assignment.

Only a digest/status leaves this helper. It does not calculate as a participant,
grant business record access, or treat old feedback as current confirmation.
"""
import hashlib
import json

LIMIT = 2000
FIELDS = {
    'stock.quant': ['quantity','reserved_quantity','location_id','lot_id','owner_id','package_id'],
    'stock.move': ['state','quantity','product_uom_qty','date','date_deadline','location_id','location_dest_id','picked','raw_material_production_id','purchase_line_id','product_uom','product_uom_id','uom_id'],
    'stock.move.line': ['quantity','state','picked','location_id','location_dest_id','lot_id','owner_id','package_id','result_package_id','move_id','product_uom_id','uom_id'],
    'purchase.order.line': ['product_qty','qty_received','date_planned','state','product_uom','product_uom_id','uom_id','order_id'],
    'purchase.order': ['state','picking_type_id','company_id'],
    'mrp.production': ['state','priority','date_start','date_finished','product_qty','product_uom_id','uom_id'],
    'stock.picking': ['state','scheduled_date','date_done','location_id','location_dest_id'],
    'stock.location': ['active','usage','location_id','company_id'],
    'stock.warehouse': ['active','lot_stock_id','view_location_id','reception_steps'],
    'product.product': ['active','product_tmpl_id'],
    'product.template': ['active','tracking','type','is_storable','uom_id'],
    'uom.uom': ['active','rounding','factor','relative_factor','relative_uom_id','category_id'],
}


def stamp(line):
    line = line.sudo().exists()
    if len(line) != 1:
        return None
    env = line.env
    company, product = line.company_id.id, line.product_id.id
    data = {}

    def collect(model, domain):
        columns = ['id'] + [f for f in FIELDS[model] if f in env[model]._fields]
        rows = env[model].with_context(active_test=False).search_read(
            domain, columns, order='id', limit=LIMIT + 1, load=False)
        if len(rows) > LIMIT:
            raise OverflowError()
        data[model] = rows
        return [r['id'] for r in rows]

    try:
        scope = [('company_id', '=', company), ('product_id', '=', product)]
        collect('stock.quant', scope)
        move_ids = collect('stock.move', scope)
        collect('stock.move.line', scope)
        line_ids = collect('purchase.order.line', scope)
        moves = env['stock.move'].browse(move_ids)
        production_ids = moves.mapped('raw_material_production_id').ids
        collect('mrp.production', [('id', 'in', production_ids)])
        # Changes in another component can invalidate the adoption checks too.
        other = env['stock.move'].search_read(
            [('raw_material_production_id', 'in', production_ids), ('product_id', '!=', product)],
            ['id'] + [f for f in FIELDS['stock.move'] if f in env['stock.move']._fields],
            order='id', limit=LIMIT + 1, load=False)
        if len(other) > LIMIT:
            return None
        data['other_components'] = other
        collect('purchase.order', [('id', 'in', env['purchase.order.line'].browse(line_ids).mapped('order_id').ids)])
        collect('stock.picking', [('id', 'in', moves.mapped('picking_id').ids)])
        collect('stock.location', [('company_id', 'in', [False, company])])
        collect('stock.warehouse', [('company_id', '=', company)])
        collect('product.product', [('id', '=', product)])
        collect('product.template', [('id', '=', line.product_id.product_tmpl_id.id)])
        collect('uom.uom', [])
        data['rule'] = 1
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    except OverflowError:
        return None


def status(saved, current):
    if not saved or not current:
        return 'unknown'
    return 'unchanged' if saved == current else 'changed'
