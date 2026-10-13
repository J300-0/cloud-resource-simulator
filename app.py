
import os
import sqlite3
from datetime import datetime, timezone

from flask import Flask, request, redirect, url_for, render_template

app = Flask(__name__)
DB = os.path.join(os.path.dirname(__file__), "cloud.db")


def connect_db():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS machines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                cpu INTEGER NOT NULL,
                ram INTEGER NOT NULL,
                storage INTEGER NOT NULL,
                workload INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Running'
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


def log_event(message):
    with connect_db() as db:
        db.execute(
            "INSERT INTO activity (message, created_at) VALUES (?, ?)",
            (message, datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            ))
        )


@app.route("/")
def dashboard():
    with connect_db() as db:
        machines = db.execute(
            "SELECT * FROM machines ORDER BY id DESC"
        ).fetchall()
        events = db.execute(
            "SELECT * FROM activity ORDER BY id DESC LIMIT 10"
        ).fetchall()

    running = [m for m in machines if m["status"] == "Running"]
    total_cpu = sum(m["cpu"] for m in running)
    total_ram = sum(m["ram"] for m in running)
    total_storage = sum(m["storage"] for m in machines)

    cpu_used = sum(
        m["cpu"] * m["workload"] / 100 for m in running
    )
    ram_used = sum(
        m["ram"] * m["workload"] / 100 for m in running
    )

    cpu_pct = round(cpu_used / total_cpu * 100) if total_cpu else 0
    ram_pct = round(ram_used / total_ram * 100) if total_ram else 0

    return render_template(
        "index.html",
        machines=machines,
        events=events,
        running_count=len(running),
        total_count=len(machines),
        total_cpu=total_cpu,
        total_ram=total_ram,
        total_storage=total_storage,
        cpu_pct=cpu_pct,
        ram_pct=ram_pct,
    )


@app.post("/create")
def create_machine():
    name = request.form.get("name", "").strip()
    try:
        cpu = int(request.form.get("cpu", 0))
        ram = int(request.form.get("ram", 0))
        storage = int(request.form.get("storage", 0))
    except ValueError:
        return "Resource values must be whole numbers.", 400

    if (
        not name or len(name) > 60
        or not 1 <= cpu <= 32
        or not 1 <= ram <= 128
        or not 1 <= storage <= 2048
    ):
        return "Invalid name or resource limits.", 400

    with connect_db() as db:
        db.execute(
            """INSERT INTO machines
               (name, cpu, ram, storage)
               VALUES (?, ?, ?, ?)""",
            (name, cpu, ram, storage)
        )

    log_event(f"Created virtual machine: {name}")
    return redirect(url_for("dashboard"))


@app.post("/workload/<int:machine_id>")
def set_workload(machine_id):
    try:
        workload = int(request.form.get("workload", -1))
    except ValueError:
        return "Workload must be a number.", 400

    if not 0 <= workload <= 100:
        return "Workload must be between 0 and 100.", 400

    with connect_db() as db:
        machine = db.execute(
            "SELECT * FROM machines WHERE id = ?", (machine_id,)
        ).fetchone()

        if machine is None:
            return "Machine not found.", 404

        if machine["status"] != "Running":
            return "Start the machine before changing workload.", 400

        db.execute(
            "UPDATE machines SET workload = ? WHERE id = ?",
            (workload, machine_id)
        )

    log_event(f"Changed workload for {machine['name']} to {workload}%")
    return redirect(url_for("dashboard"))


@app.post("/toggle/<int:machine_id>")
def toggle_machine(machine_id):
    with connect_db() as db:
        machine = db.execute(
            "SELECT * FROM machines WHERE id = ?", (machine_id,)
        ).fetchone()

        if machine is None:
            return "Machine not found.", 404

        new_status = (
            "Stopped" if machine["status"] == "Running" else "Running"
        )

        db.execute(
            "UPDATE machines SET status = ?, workload = ? WHERE id = ?",
            (new_status, 0 if new_status == "Stopped"
             else machine["workload"], machine_id)
        )

    log_event(f"{new_status} virtual machine: {machine['name']}")
    return redirect(url_for("dashboard"))


@app.post("/scale")
def scale():
    with connect_db() as db:
        machines = db.execute(
            "SELECT * FROM machines WHERE status = 'Running'"
        ).fetchall()

        if not machines:
            return "Create and start a machine before scaling.", 400

        average = sum(m["workload"] for m in machines) / len(machines)

        if average > 75 and len(machines) < 10:
            source = machines[0]
            name = f"Auto-VM-{datetime.now().strftime('%H%M%S')}"

            db.execute(
                """INSERT INTO machines
                   (name, cpu, ram, storage, workload)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, source["cpu"], source["ram"],
                 source["storage"], 0)
            )
            message = f"Scale-out simulated: created {name}"
        elif average < 25 and len(machines) > 1:
            target = machines[-1]
            db.execute(
                "UPDATE machines SET status = 'Stopped' WHERE id = ?",
                (target["id"],)
            )
            message = f"Scale-in simulated: stopped {target['name']}"
        else:
            message = f"No scaling required; average workload is {average:.0f}%."

    log_event(message)
    return redirect(url_for("dashboard"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
