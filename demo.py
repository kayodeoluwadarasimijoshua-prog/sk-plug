"""Synthetic demonstrations only. Never import a previous client's database."""

import json
from pathlib import Path


def seed(app):
    with app.app_context():
        for index, category in enumerate(app.config["STORE"]["categories"]):
            pid = "demo-" + str(index)
            app.db().execute(
                "INSERT OR IGNORE INTO products(id,name,category,price,description,images,variants,published,sample) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    category + " — demonstration",
                    category,
                    (index + 1) * 1250000,
                    "Demonstration only. Illustrative image and price. Not actual inventory; replace before launch.",
                    json.dumps(
                        [
                            (
                                "/static/demo-gadget.svg"
                                if app.config["STORE"]["layout"] == "electronics"
                                else "/static/demo-object.svg"
                            )
                        ]
                    ),
                    json.dumps(
                        [
                            {
                                "id": pid + "-one",
                                "size": "Standard",
                                "colour": "Default",
                                "stock": 5,
                            }
                        ]
                    ),
                    1,
                    1,
                ),
            )
        app.db().commit()
