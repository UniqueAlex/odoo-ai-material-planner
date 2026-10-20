"""Bounded Odoo 19 adapter; ORM reads always run as the requesting user."""

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

from odoo.exceptions import AccessError, UserError

from ..core import Demand, MaterialSnapshot, Supply, analyze


MODELS = (
    "purchase.order", "purchase.order.line", "stock.move", "stock.move.line",
    "stock.quant", "mrp.production", "stock.warehouse", "stock.location", "stock.picking",
)
MAX_RECORDS = 2000


def record_uom(record):
    """Odoo20 standardizes units as uom_id; Odoo19 uses model-specific names."""
    for name in ("uom_id", "product_uom_id", "product_uom"):
        if name in record._fields:
            unit = record[name]
            if unit and unit._name == "uom.uom":
                return unit
    raise UserError(record.env._("The material unit is unavailable."))


def unit_precision(env, unit):
    if "rounding" in unit._fields:
        return Decimal(str(unit.rounding))
    # Odoo20's uom.round/compare use the configured Product Unit precision.
    digits = env["decimal.precision"].precision_get("Product Unit")
    if type(digits) is not int or not 0 <= digits <= 12:
        raise UserError(env._("The material unit precision is unsupported."))
    return Decimal("10") ** -digits


def check_scope(env):
    for group in ("purchase.group_purchase_user", "stock.group_stock_user", "mrp.group_mrp_user"):
        if not env.user.has_group(group):
            raise AccessError(env._("Purchase, inventory and manufacturing read access are required."))
    for name in MODELS:
        env[name].check_access("read")
        # Restrictive custom rules could silently hide competing supply/demand.
        # Only unrestricted or company-only visibility is supported by v0.1.
        if "ir.rule" in env.registry.models:
            domain = list(env["ir.rule"]._compute_domain(name, "read"))
        else:
            # Odoo20 unifies ACLs and record restrictions as ir.access domains.
            access_domain = env[name]._access_domain("read")
            domain = [] if access_domain.is_true() else list(access_domain)
        if domain and not (
            len(domain) == 1 and isinstance(domain[0], tuple)
            and domain[0][0:2] == ("company_id", "in")
            and set(env.companies.ids).issubset(set(domain[0][2]))
        ):
            raise UserError(env._("Custom record restrictions prevent a complete material snapshot. Ask an administrator to review access."))


def checked_order(env, order_id):
    check_scope(env)
    order = env["purchase.order"].browse(order_id).exists()
    if len(order) != 1:
        raise UserError(env._("The purchase order is unavailable."))
    order.check_access("read")
    if order.company_id.id not in env.companies.ids or order.state not in ("purchase", "done"):
        raise UserError(env._("Select a confirmed purchase order in an allowed company."))
    return order


def options(env, order_id):
    order = checked_order(env, order_id)
    lines = []
    for line in order.order_line:
        if not line.display_type and line.product_id.is_storable and line.product_qty > line.qty_received:
            line.check_access("read")
            lines.append({
                "id": line.id, "product": line.product_id.display_name,
                "pending": line.product_qty - line.qty_received,
                "unit": record_uom(line).name,
                "planned_at": utc(line.date_planned, env).isoformat(),
            })
    if not lines:
        raise UserError(env._("This order has no pending stock-tracked material lines."))
    return {"order": order.name, "lines": lines, "timezone": env.user.tz or None}


def utc(value, env):
    if not isinstance(value, datetime):
        raise UserError(env._("A verified date and time are required for every supply and demand."))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def bounded_search(env, model, domain):
    records = env[model].search(domain, limit=MAX_RECORDS + 1)
    if len(records) > MAX_RECORDS:
        raise UserError(env._("This material exceeds the prototype's record limit."))
    return records


def calculate(env, order_id, line_id, assumed_at, with_ai=False, *, include_snapshot=False):
    if include_snapshot and with_ai:
        raise ValueError("Snapshot capture and AI preparation are separate requests")
    order = checked_order(env, order_id)
    line = env["purchase.order.line"].browse(line_id).exists()
    if len(line) != 1:
        raise UserError(env._("The selected purchase line is unavailable."))
    line.check_access("read")
    if line.order_id != order or line.display_type:
        raise AccessError(env._("The selected line does not belong to this purchase order."))
    product = line.product_id
    product.check_access("read")
    if not product.is_storable or product.tracking not in (False, "none"):
        raise UserError(env._("This prototype supports stock-tracked materials without lot or serial constraints."))
    warehouse = order.picking_type_id.warehouse_id
    warehouses = env["stock.warehouse"].search([("company_id", "=", order.company_id.id)])
    if len(warehouses) != 1 or warehouse != warehouses or warehouse.reception_steps != "one_step":
        raise UserError(env._("This prototype requires one warehouse and one-step receipts in the selected company."))
    if order.picking_type_id.code != "incoming":
        raise UserError(env._("Only direct warehouse purchase receipts are supported."))
    locations = env["stock.location"].search([
        ("id", "child_of", warehouse.view_location_id.id),
        ("usage", "=", "internal"), ("company_id", "=", order.company_id.id),
    ])
    if not locations:
        raise UserError(env._("No accessible internal stock location was found."))
    precision = unit_precision(env, product.uom_id)

    def quantity(value, unit=None):
        converted = unit._compute_quantity(value, product.uom_id, round=False) if unit else value
        raw = Decimal(str(converted))
        rounded = (raw / precision).to_integral_value(rounding=ROUND_HALF_UP) * precision
        if abs(rounded - raw) > precision * Decimal("0.000001"):
            raise UserError(env._("A quantity cannot be normalized to the material's unit precision."))
        return rounded

    quants = bounded_search(env, "stock.quant", [
        ("company_id", "=", order.company_id.id), ("product_id", "=", product.id),
        ("location_id", "in", locations.ids),
    ])
    if any(q.owner_id or q.lot_id or q.package_id or q.quantity < 0 for q in quants):
        raise UserError(env._("Owned, packaged, lot-restricted or negative stock requires a separate calculation scope."))
    on_hand = sum((quantity(q.quantity) for q in quants), Decimal("0"))
    quant_reserved = sum((quantity(q.reserved_quantity) for q in quants), Decimal("0"))
    active_moves = bounded_search(env, "stock.move", [
        ("company_id", "=", order.company_id.id), ("product_id", "=", product.id),
        ("state", "not in", ["done", "cancel"]),
        "|", ("location_id", "in", locations.ids), ("location_dest_id", "in", locations.ids),
    ])
    supplies, demands, evidence = [], [], []
    incoming_by_line = {}
    reserved_total = Decimal("0")
    stock_ref = "stock.quants:" + ",".join(map(str, sorted(quants.ids)))
    evidence.append({"ref": stock_ref, "kind": "stock", "label": product.display_name,
                     "quantity": float(on_hand), "reserved": float(quant_reserved),
                     "model": "product.product", "id": product.id})
    unit = product.uom_id.name
    for move in active_moves:
        move.check_access("read")
        if move.picked or move.move_orig_ids or move.move_dest_ids:
            raise UserError(env._("Picked material or linked replenishment routes are outside this prototype's scope."))
        qty = quantity(move.product_uom_qty, record_uom(move))
        if qty <= 0:
            raise UserError(env._("An active material move has no positive remaining demand."))
        ref = f"stock.move:{move.id}"
        if move.location_id.usage == "supplier" and move.location_dest_id in locations and move.purchase_line_id:
            purchase_line = move.purchase_line_id
            purchase_line.check_access("read")
            if purchase_line.order_id.state not in ("purchase", "done") or purchase_line.order_id.picking_type_id.warehouse_id != warehouse:
                raise UserError(env._("An incoming move does not match a confirmed warehouse purchase."))
            at = utc(move.date, env)
            supply_line_ref = f"purchase.order.line:{purchase_line.id}"
            supplies.append(Supply(ref, supply_line_ref, qty, at, unit))
            incoming_by_line[purchase_line.id] = incoming_by_line.get(purchase_line.id, Decimal("0")) + qty
            evidence.append({"ref": ref, "kind": "receipt", "label": move.picking_id.name,
                             "purchase": purchase_line.order_id.name, "state": move.state, "receipt_status": "pending", "quantity": float(qty),
                             "at": at.isoformat(), "model": "stock.picking", "id": move.picking_id.id})
        elif move.location_id in locations and move.location_dest_id.usage == "production" and move.raw_material_production_id:
            mo = move.raw_material_production_id
            mo.check_access("read")
            if mo.state != "confirmed" or mo.qty_producing or mo.qty_produced:
                raise UserError(env._("Only confirmed manufacturing orders with no production recorded are supported."))
            if mo.picking_type_id.warehouse_id != warehouse:
                raise UserError(env._("A manufacturing order uses a different warehouse."))
            move_lines = env["stock.move.line"].search([("move_id", "=", move.id)])
            if any(ml.picked or ml.lot_id or ml.owner_id or ml.package_id or ml.location_id not in locations for ml in move_lines):
                raise UserError(env._("A material reservation has unsupported ownership, location or picking constraints."))
            reserved = sum((quantity(ml.quantity, record_uom(ml)) for ml in move_lines), Decimal("0"))
            if reserved != quantity(move.quantity, record_uom(move)):
                raise UserError(env._("Material move quantities do not agree with reservation evidence."))
            reserved_total += reserved
            at = utc(mo.date_start, env)
            # Separate raw moves stay separate evidence rows even on the same MO.
            demands.append(Demand(ref, qty, reserved, at, unit))
            evidence.append({"ref": ref, "kind": "manufacturing", "label": mo.name,
                             "quantity": float(qty), "reserved": float(reserved), "at": at.isoformat(),
                             "model": "mrp.production", "id": mo.id})
        else:
            raise UserError(env._("Other transfers, deliveries or replenishment sources compete for this material. The prototype cannot give a complete result."))
    for purchase_line_id, incoming in incoming_by_line.items():
        purchase_line = env["purchase.order.line"].browse(purchase_line_id)
        pending = quantity(purchase_line.product_qty - purchase_line.qty_received, record_uom(purchase_line))
        if pending != incoming:
            raise UserError(env._("Pending receipts do not reconcile with a purchase line's unreceived quantity."))
    if reserved_total != quant_reserved:
        raise UserError(env._("Stock reservations do not reconcile with the included manufacturing demands."))
    env.cr.execute("SELECT transaction_timestamp()")
    taken_at = env.cr.fetchone()[0].astimezone(timezone.utc)
    snapshot = MaterialSnapshot(
        ref="pending", taken_at=taken_at, company_ref=str(order.company_id.id),
        warehouse_ref=str(warehouse.id), product_ref=str(product.id), unit=unit, precision=precision,
        stock_ref=stock_ref, on_hand=on_hand, supplies=tuple(supplies), demands=tuple(demands),
    )
    snapshot_id = hashlib.sha256(json.dumps(asdict(snapshot), default=str, sort_keys=True).encode()).hexdigest()[:16]
    try:
        result = analyze(snapshot, f"purchase.order.line:{line.id}", assumed_at)
    except ValueError as exc:
        raise UserError(env._("The material scenario cannot be calculated: %s", str(exc))) from exc
    evidence_by_ref = {item["ref"]: item for item in evidence}
    rows = []
    for baseline, delayed, impact in zip(result.baseline.demands, result.delayed.demands, result.impacts, strict=True):
        source = evidence_by_ref[impact.ref]
        rows.append({
            "ref": impact.ref, "mo": source["label"], "mo_id": source["id"],
            "need_at": delayed.need_at.isoformat(), "quantity": float(delayed.quantity),
            "reserved": float(delayed.reserved), "baseline_shortage": float(impact.baseline_shortage),
            "delayed_shortage": float(impact.delayed_shortage), "new_shortage": float(impact.new_shortage),
            "unfilled": float(delayed.quantity - sum((a.quantity for a in delayed.allocations), Decimal("0"))),
            "full_at": impact.delayed_full_at.isoformat() if impact.delayed_full_at else None,
            "change": impact.change, "grade": impact.coverage_grade,
            "allocations": [{"ref": a.source_ref, "quantity": float(a.quantity), "at": a.available_at.isoformat()}
                            for a in delayed.allocations],
        })
    report = {
        "snapshot_id": snapshot_id, "taken_at": snapshot.taken_at.isoformat(),
        "order": order.name, "line_id": line.id, "product": product.display_name,
        "company": order.company_id.display_name, "warehouse": warehouse.display_name, "unit": unit,
        "on_hand": float(on_hand), "reserved": float(quant_reserved),
        "pending": float(incoming_by_line.get(line.id, Decimal("0"))), "assumed_at": assumed_at.isoformat(),
        "planned_at": utc(line.date_planned, env).isoformat(),
        "unallocated": float(result.delayed.unallocated), "unfilled": float(result.delayed.unfilled),
        "rows": rows, "evidence": evidence,
        "rule_version": "0.1", "transaction_read_only": True,
    }
    if not with_ai:
        return (report, snapshot, result) if include_snapshot else report
    def purchase_fact(purchase_line):
        return {"line_ref": f"purchase.order.line:{purchase_line.id}", "order_ref": purchase_line.order_id.name,
                "ordered": float(quantity(purchase_line.product_qty, record_uom(purchase_line))),
                "received": float(quantity(purchase_line.qty_received, record_uom(purchase_line))),
                "pending": float(incoming_by_line.get(purchase_line.id, Decimal("0"))),
                "planned_at": utc(purchase_line.date_planned, env).isoformat()}
    receipt_moves = bounded_search(env, "stock.move", [("purchase_line_id", "=", line.id),
        ("product_id", "=", product.id), ("company_id", "=", order.company_id.id)])
    receipts = [{"move_ref": f"stock.move:{move.id}", "receipt_ref": move.picking_id.name,
                 "state": move.state, "quantity": float(quantity(move.quantity if move.state == "done" else move.product_uom_qty, record_uom(move))),
                 "at": utc(move.date, env).isoformat(), "order_ref": order.name} for move in receipt_moves]
    rank = {"low": 0, "medium": 1, "high": 2}
    other_incoming = []
    for identifier in sorted(incoming_by_line):
        if identifier == line.id:
            continue
        fact = purchase_fact(env["purchase.order.line"].browse(identifier))
        fact["receipts"] = [{"move_ref": supply.ref,
            "receipt_ref": evidence_by_ref[supply.ref]["label"], "state": evidence_by_ref[supply.ref]["state"],
            "receipt_status": "pending", "quantity": float(supply.quantity),
            "at": supply.available_at.isoformat()} for supply in supplies
            if supply.purchase_line_ref == fact["line_ref"]]
        other_incoming.append(fact)
    grade = max((row["grade"] for row in rows), key=lambda g: rank[g], default="low")
    def labeled_allocations(row):
        allocations = []
        for allocation in row["allocations"]:
            ref = allocation["ref"]
            if ref.startswith(stock_ref + ":reserved:"):
                source = {"source_kind": "reserved_stock", "source_name": "Stock reserved for " + row["mo"]}
            elif ref == stock_ref + ":unreserved":
                source = {"source_kind": "unreserved_stock", "source_name": "Unreserved current stock"}
            else:
                receipt = evidence_by_ref[ref]
                source = {"source_kind": "purchase_receipt", "source_name": receipt["purchase"] + " / " + receipt["label"],
                          "order_ref": receipt["purchase"], "receipt_ref": receipt["label"],
                          "record_state": receipt["state"], "receipt_status": "pending"}
            allocations.append({**allocation, **source})
        return allocations
    calculations = [{"demand_ref": row["ref"], "mo_ref": row["mo"], "need_at": row["need_at"],
                     "baseline_shortage": row["baseline_shortage"], "hypothetical_shortage": row["delayed_shortage"],
                     "new_shortage": row["new_shortage"], "material_full_at": row["full_at"],
                     "unfilled": row["unfilled"],
                     "evidence_ref": f"calc:{snapshot_id}:{row['ref']}", "allocations": labeled_allocations(row)} for row in rows]
    used_by_source = {}
    for demand in result.delayed.demands:
        for allocation in demand.allocations:
            ref = allocation.source_ref
            used_by_source[ref] = used_by_source.get(ref, Decimal("0")) + allocation.quantity
    stock_available = on_hand - quant_reserved
    stock_used = used_by_source.get(stock_ref + ":unreserved", Decimal("0"))
    source_balances = [{"source_ref": stock_ref + ":unreserved", "source_name": "Unreserved current stock",
        "source_kind": "unreserved_stock", "available": float(stock_available), "allocated": float(stock_used),
        "original_available_at": snapshot.taken_at.isoformat(), "scenario_available_at": snapshot.taken_at.isoformat(),
        "unallocated": float(stock_available - stock_used)}]
    remaining_total = stock_available - stock_used
    for supply in supplies:
        source = evidence_by_ref[supply.ref]
        used = used_by_source.get(supply.ref, Decimal("0"))
        remainder = supply.quantity - used
        if remainder < 0:
            raise UserError(env._("Scenario allocations exceed the known source quantity."))
        remaining_total += remainder
        source_balances.append({"source_ref": supply.ref, "source_kind": "purchase_receipt",
            "source_name": source["purchase"] + " / " + source["label"], "order_ref": source["purchase"],
            "receipt_ref": source["label"], "record_state": source["state"], "receipt_status": "pending",
            "original_available_at": supply.available_at.isoformat(),
            "scenario_available_at": (assumed_at if supply.purchase_line_ref == f"purchase.order.line:{line.id}"
                                      else supply.available_at).isoformat(),
            "available": float(supply.quantity), "allocated": float(used),
            "unallocated": float(remainder)})
    if remaining_total != result.delayed.unallocated or stock_available < stock_used:
        raise UserError(env._("Scenario source balances do not reconcile with the remaining quantity."))
    report["source_balances"] = source_balances
    task = {"snapshot_id": snapshot_id, "order_ref": order.name, "grade": grade,
            "context": {"purchase": order.name, "line_ref": f"purchase.order.line:{line.id}",
                        "material": product.display_name, "unit": unit, "pending": report["pending"],
                        "original_planned_at": purchase_fact(line)["planned_at"],
                        "assumed_at": report["assumed_at"], "taken_at": report["taken_at"], "rule_version": "0.1"},
            "tools": {
                "read_purchase_line": purchase_fact(line), "read_receipts": receipts,
                "read_stock_reservations": {"stock_ref": stock_ref, "on_hand": report["on_hand"],
                    "reserved": report["reserved"], "demands": [{"demand_ref": row["ref"], "mo_ref": row["mo"],
                    "reserved": row["reserved"]} for row in rows]},
                "read_other_incoming": other_incoming,
                "read_material_demands": [{"demand_ref": row["ref"], "mo_ref": row["mo"], "need_at": row["need_at"],
                    "quantity": row["quantity"], "reserved": row["reserved"]} for row in rows],
                "read_calculation_evidence": calculations,
                "read_data_quality": {"company": report["company"], "warehouse": report["warehouse"],
                    "complete": True, "transaction_read_only": True, "material_only": True,
                    "does_not_predict_mo_completion": True, "rule_version": "0.1", "unfilled": report["unfilled"],
                    "allocations_are_simulated": True, "purchase_to_mo_hard_link": False,
                    "does_not_assert_source_exclusivity": True,
                    "source_balances": source_balances,
                    "balance_scope": "After all known scenario events; not current stock or a receipt's physical remainder today.",
                    "unallocated": report["unallocated"], "limits": "One material, one warehouse, one-step receipts, confirmed unstarted MOs, no lot/owner/package constraints."},
            }}
    return report, task
