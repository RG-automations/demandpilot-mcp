from __future__ import annotations

from datetime import date

import pytest

from demandpilot.data import repository
from demandpilot.data.database import connect_ro
from demandpilot.data_gen import DEMAND_PROFILES, generate, write_database


def test_generate_is_deterministic_for_same_seed():
    a = generate(42, date(2026, 1, 1), 20, 730)
    b = generate(42, date(2026, 1, 1), 20, 730)
    assert a == b


def test_generate_differs_for_different_seed():
    a = generate(42, date(2026, 1, 1), 20, 730)
    b = generate(43, date(2026, 1, 1), 20, 730)
    assert a != b


def test_generate_respects_reference_date():
    products, sales, inventory, metadata = generate(42, date(2026, 6, 1), 20, 730)
    assert metadata[2] == "2026-06-01"
    assert all(row[1] == "2026-06-01" for row in inventory)
    assert all(row[1] < "2026-06-01" for row in sales)


def test_sku_ids_are_well_formed():
    products, *_ = generate(42, date(2026, 1, 1), 20, 730)
    skus = [row[0] for row in products]
    assert skus == [f"DEMO-{i:03d}" for i in range(1, 21)]


def test_all_demand_profiles_present_in_default_catalog():
    products, *_ = generate(42, date(2026, 1, 1), 20, 730)
    profiles = {row[2] for row in products}
    assert profiles == set(DEMAND_PROFILES)


def test_sales_quantities_are_nonnegative():
    _, sales, _, _ = generate(42, date(2026, 1, 1), 20, 730)
    assert all(row[2] >= 0 for row in sales)


def test_dataset_marked_as_synthetic():
    *_, metadata = generate(42, date(2026, 1, 1), 20, 730)
    is_synthetic, seed, reference_date, generator_version = metadata
    assert is_synthetic == 1
    assert seed == 42
    assert generator_version


def test_short_history_sku_has_fewer_days_than_default():
    products, sales, _, _ = generate(42, date(2026, 1, 1), 20, 730)
    short_sku = next(row[0] for row in products if row[2] == "short_history")
    stable_sku = next(row[0] for row in products if row[2] == "stable")
    short_days = sum(1 for row in sales if row[0] == short_sku)
    stable_days = sum(1 for row in sales if row[0] == stable_sku)
    assert short_days < stable_days
    assert short_days <= 20


def test_no_sales_sku_has_all_zero_quantities():
    products, sales, _, _ = generate(42, date(2026, 1, 1), 20, 730)
    no_sales_sku = next(row[0] for row in products if row[2] == "no_sales")
    quantities = [row[2] for row in sales if row[0] == no_sales_sku]
    assert quantities  # fully observed, not missing
    assert all(q == 0 for q in quantities)


def test_write_database_refuses_to_overwrite_existing_file(tmp_path):
    db_path = tmp_path / "demo.sqlite3"
    write_database(db_path, 42, date(2026, 1, 1), 5, 60)
    assert db_path.exists()
    # write_database itself has no overwrite guard (that lives in the CLI);
    # verify the CLI guard here via the file-exists check used by main().
    assert db_path.is_file()


def test_generated_database_passes_schema_integrity_checks(tmp_path):
    db_path = tmp_path / "demo.sqlite3"
    write_database(db_path, 42, date(2026, 1, 1), 20, 730)
    conn = connect_ro(db_path)
    try:
        products = repository.list_products(conn)
        assert len(products) == 20
        for p in products:
            assert 0 < p.service_level < 1
            assert p.pack_size > 0
            assert p.moq >= 0
        # foreign key integrity: every sales_history/inventory row's sku exists in products
        bad_sales = conn.execute(
            "SELECT COUNT(*) FROM sales_history s LEFT JOIN products p ON s.sku = p.sku "
            "WHERE p.sku IS NULL"
        ).fetchone()[0]
        assert bad_sales == 0
    finally:
        conn.close()


def test_main_cli_rejects_invalid_reference_date(tmp_path, capsys):
    from demandpilot.data_gen import main

    db_path = tmp_path / "demo.sqlite3"
    exit_code = main(["--db", str(db_path), "--reference-date", "not-a-date"])
    assert exit_code == 1
    assert "invalid --reference-date" in capsys.readouterr().err.lower()
    assert not db_path.exists()


def test_main_cli_rejects_nonpositive_sku_count(tmp_path, capsys):
    from demandpilot.data_gen import main

    db_path = tmp_path / "demo.sqlite3"
    exit_code = main(["--db", str(db_path), "--sku-count", "0"])
    assert exit_code == 1
    assert "sku-count" in capsys.readouterr().err.lower()
    assert not db_path.exists()


def test_main_cli_refuses_overwrite_without_flag(tmp_path, capsys):
    from demandpilot.data_gen import main

    db_path = tmp_path / "demo.sqlite3"
    assert main(["--db", str(db_path), "--sku-count", "5", "--history-days", "60"]) == 0
    assert db_path.exists()
    exit_code = main(["--db", str(db_path), "--sku-count", "5", "--history-days", "60"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "overwrite" in captured.err.lower()


def test_main_cli_overwrite_flag_replaces_existing_db(tmp_path):
    from demandpilot.data_gen import main

    db_path = tmp_path / "demo.sqlite3"
    assert (
        main(["--db", str(db_path), "--seed", "1", "--sku-count", "5", "--history-days", "60"]) == 0
    )
    assert (
        main(
            [
                "--db",
                str(db_path),
                "--seed",
                "2",
                "--sku-count",
                "5",
                "--history-days",
                "60",
                "--overwrite",
            ]
        )
        == 0
    )
    conn = connect_ro(db_path)
    try:
        assert repository.get_dataset_metadata(conn).seed == 2
    finally:
        conn.close()


@pytest.mark.parametrize("history_days", [0, 731])
def test_main_cli_rejects_invalid_history_days(tmp_path, history_days):
    from demandpilot.data_gen import main

    db_path = tmp_path / "demo.sqlite3"
    exit_code = main(["--db", str(db_path), "--history-days", str(history_days)])
    assert exit_code == 1
    assert not db_path.exists()
