"""Back up and update the explicitly selected development database."""
import argparse
import configparser
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys

import psycopg2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    config = configparser.ConfigParser()
    config_path = root / "config" / "odoo-dev.conf"
    config.read(config_path)
    options = config["options"]
    dump_binary = shutil.which("pg_dump")
    if not dump_binary:
        candidates = sorted((Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PostgreSQL").glob("*/bin/pg_dump.exe"))
        dump_binary = str(candidates[-1]) if candidates else None
    if not dump_binary:
        raise RuntimeError("pg_dump is required for the database backup. No update was applied.")
    connection_args = dict(dbname=args.database, host=options["db_host"], port=options["db_port"],
                           user=options["db_user"], password=options.get("db_password"))
    with psycopg2.connect(**connection_args) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT state FROM ir_module_module WHERE name = %s", ["pos_auto_variant_price_rounding"])
            if cursor.fetchone() != ("installed",):
                raise RuntimeError("The selected database must already have this addon installed.")
    folder = root / "tmp" / ("variant_price_update_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    folder.mkdir(parents=True)
    backup = folder / "database.dump"
    environment = os.environ.copy()
    environment.update(PGPASSWORD=options.get("db_password", ""), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    subprocess.run([dump_binary, "-h", options["db_host"], "-p", options["db_port"], "-U", options["db_user"],
                    "-d", args.database, "-Fc", "-f", str(backup)], env=environment, check=True)
    print("Database backup:", backup, flush=True)
    log = folder / "upgrade.log"
    result = subprocess.run([
        str(root / "python" / "python.exe"), str(root / "server" / "odoo-bin"),
        "-c", str(config_path), "-d", args.database, "-u", "pos_auto_variant_price_rounding",
        "--stop-after-init", "--no-http", "--max-cron-threads=0", "--http-port=0", "--logfile=" + str(log),
    ], cwd=root / "server", env=environment)
    print("Upgrade log:", log, flush=True)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
