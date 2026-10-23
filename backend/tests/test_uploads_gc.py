"""The uploads sweep: what it keeps, what it reclaims, and what it refuses."""

import asyncio
import pathlib
import re

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.uploads_gc import EmptyDatabaseError, cleanup_uploads


def test_a_restaurant_cover_keeps_its_file(client, register, create_restaurant, upload_image, sweep, uploads_dir):
    _, headers = register(role="restaurant_admin")
    uploaded = upload_image(headers)
    create_restaurant(headers, image_url=uploaded["url"])

    report = sweep(delete=True, min_age_minutes=0)

    assert report.referenced_names == 1
    assert report.deleted == []
    assert (uploads_dir / uploaded["filename"]).exists()


def test_a_menu_item_image_keeps_its_file(
    client, register, create_restaurant, upload_image, sweep, uploads_dir
):
    """The harder case: the only reference lives inside the JSON menu column."""
    _, headers = register(role="restaurant_admin")
    restaurant = create_restaurant(headers)
    uploaded = upload_image(headers)
    client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu",
        json=[{"name": "Dish", "price": 3.5, "image_url": uploaded["url"]}],
        headers=headers,
    )

    report = sweep(delete=True, min_age_minutes=0)

    assert report.deleted == []
    assert (uploads_dir / uploaded["filename"]).exists()


def test_an_unreferenced_aged_file_is_reported_and_a_dry_run_deletes_nothing(
    sweep, managed_upload, sweep_log
):
    orphan = managed_upload()

    report = sweep()  # delete defaults to False

    assert [path.name for path in report.orphans] == [orphan.name]
    assert report.deleted == []
    assert orphan.exists()

    text = sweep_log.read_text()
    assert "dry run" in text
    assert f"would delete: {orphan.name}" in text


def test_deleting_reclaims_only_the_orphans(
    client, register, create_restaurant, upload_image, managed_upload, sweep, uploads_dir
):
    _, headers = register(role="restaurant_admin")
    kept = upload_image(headers)
    create_restaurant(headers, image_url=kept["url"])
    first = managed_upload()
    second = managed_upload()

    report = sweep(delete=True, min_age_minutes=0)

    assert sorted(path.name for path in report.deleted) == sorted([first.name, second.name])
    assert report.deleted_bytes > 0
    assert not first.exists() and not second.exists()
    assert (uploads_dir / kept["filename"]).exists()


def test_a_fresh_file_is_protected_by_the_age_guard(sweep, managed_upload, populated_database):
    fresh = managed_upload(age_minutes=1)

    guarded = sweep(delete=True)  # default 60-minute floor

    assert [path.name for path in guarded.too_new] == [fresh.name]
    assert guarded.orphans == [] and guarded.deleted == []
    assert fresh.exists()

    unguarded = sweep(delete=True, min_age_minutes=0)
    assert [path.name for path in unguarded.deleted] == [fresh.name]
    assert not fresh.exists()


def test_files_we_did_not_create_are_left_alone(sweep, managed_upload, populated_database):
    handwritten = managed_upload(name="receipt.png")  # not the uuid naming we generate

    report = sweep(delete=True, min_age_minutes=0)

    assert report.unmanaged == ["receipt.png"]
    assert report.orphans == [] and report.deleted == []
    assert handwritten.exists()


def test_log_entries_label_each_file_by_what_actually_happened(
    sweep, managed_upload, sweep_log, populated_database
):
    orphan = managed_upload()

    sweep()
    assert re.search(rf"^  would delete: {orphan.name}", sweep_log.read_text(), re.M)

    sweep(delete=True, min_age_minutes=0)
    text = sweep_log.read_text()
    assert re.search(rf"^  deleted: {orphan.name}", text, re.M)
    assert "would delete" in text, "the earlier dry run stays in the history"


def test_idle_runs_can_be_left_out_of_the_log(sweep, sweep_log):
    report = sweep(log_idle=False)  # what the background sweep does

    assert report.is_idle()
    assert not sweep_log.exists()

    sweep()  # a deliberate run is still recorded
    assert sweep_log.exists()


def test_an_empty_database_refuses_to_delete(sweep_log, managed_upload, tmp_path):
    """The guard against sweeping with the wrong DATABASE_URL.

    Deliberately does not use `populated_database`: this is the one case where an
    empty database is the point.
    """
    orphan = managed_upload()

    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'empty.db').as_posix()}")
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await cleanup_uploads(session, delete=True, min_age_minutes=0)
        finally:
            await engine.dispose()

    with pytest.raises(EmptyDatabaseError):
        asyncio.run(run())

    assert orphan.exists(), "a refusal must not delete anything"
    assert "refused:" in sweep_log.read_text()


def test_a_file_that_vanishes_mid_sweep_is_not_an_error(
    monkeypatch, sweep, managed_upload, populated_database
):
    """Two sweeps (or a human) can race; losing the race must not be a crash."""
    orphan = managed_upload()
    real_unlink = pathlib.Path.unlink

    def vanishing(self, *args, **kwargs):
        if self.name == orphan.name:
            raise FileNotFoundError(str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", vanishing)

    report = sweep(delete=True, min_age_minutes=0)

    assert report.orphans and report.deleted == []
    assert report.deleted_bytes == 0
