{
    "name": "AI Material Planner",
    "summary": "Compare purchase delay and material allocation options with shared reviews",
    "description": """Purchase delay scenarios, material allocation comparisons and shared reviews.
Optional AI sends the selected material's purchase/receipt references, quantities,
stock/reservations, incoming supply, manufacturing needs and calculation evidence
directly to the configured provider after the user's informed action. Prices,
contacts, free-form business notes and the whole database are excluded.
The module is free. AI requires the customer's own provider account and API key;
provider usage fees are separate. No vendor activation key is required.
Only material availability is simulated; purchases, stock and manufacturing orders
are not automatically changed. Review tasks and decisions are saved in Odoo.
Validated configurations: native Windows 11 Odoo 19 (workers=0) and Ubuntu 24.04 with Odoo 19 Docker (two HTTP workers).
See the included acceptance record for tested versions and worker configuration.
Odoo.sh requires separate platform acceptance. Odoo Online is not supported.
See static/description/index.html and the included delivery documentation.
""",
    "version": "19.0.1.1.0",
    "category": "Manufacturing",
    "author": "Material Delay Impact project",
    "images": ["static/description/cover.png"],
    "support": "aa7266901@gmail.com",
    "price": 0.0,
    "currency": "EUR",
    "license": "LGPL-3",
    "depends": ["purchase_stock", "mrp", "web"],
    "external_dependencies": {"python": ["requests", "cryptography"]},
    "data": ["views/purchase_order_views.xml", "views/review_activity_views.xml"],
    "assets": {
        "web.assets_backend": [
            "material_delay_impact/static/src/review_inbox.js",
            "material_delay_impact/static/src/review_inbox.xml",
            "material_delay_impact/static/src/reallocation_panel.js",
            "material_delay_impact/static/src/reallocation_panel.xml",
            "material_delay_impact/static/src/delay_action.js",
            "material_delay_impact/static/src/delay_action.xml",
            "material_delay_impact/static/src/delay_action.scss",
        ],
    },
    "installable": True,
    "application": False,
}
